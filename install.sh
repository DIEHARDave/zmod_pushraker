#!/bin/sh
# zmod_pushraker - run by Zmod's ENABLE_PLUGIN name=zmod_pushraker (and,
# rerun by hand, to repair the links after a Zmod update).
#
# On the host (Klipper):   links klipper/pushraker_hooks.py into Klipper's
#                          extras.
# In Zmod's chroot (Moonraker): links moonraker/pushraker.py and
#                          pushraker_cards.py into Moonraker's components,
#                          includes zmod_pushraker.moonraker.conf, compiles
#                          the package, starts the settings page on port 82.
# Then asks Zmod for a reboot, so Klipper and Moonraker load it all.

[ -f /opt/config/mod/.shell/0.sh ] && . /opt/config/mod/.shell/0.sh
[ -f /usr/data/zmod/zmod/.shell/0.sh ] && . /usr/data/zmod/zmod/.shell/0.sh

set -eu

NAME=zmod_pushraker
# /opt/config is the config folder both on the host and in the chroot.
CHROOT_PLUGIN_DIR="/opt/config/mod_data/plugins/$NAME"
PLUGIN_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
CONFIG_DIR=$(CDPATH= cd -- "$PLUGIN_DIR/../../.." && pwd -P)

# ---- host: Klipper ---------------------------------------------------------
if [ ! -f /ZMOD ] && [ -z "${ZMOD_PUSHRAKER_CHROOT:-}" ]; then
    MODULE=pushraker_hooks.py
    SOURCE="$PLUGIN_DIR/klipper/$MODULE"
    linked=0
    # The AD5X can have both the native Klipper and Zmod's Klipper 13: link
    # into every extras directory rather than guessing which one runs.
    for EXTRAS_DIR in \
        /usr/prog/klipper/klippy/extras \
        /usr/data/zmod/klipper/klippy/extras \
        ${KLIPPER_DIR:+"$KLIPPER_DIR/klippy/extras"}
    do
        [ -d "$EXTRAS_DIR" ] || continue
        TARGET="$EXTRAS_DIR/$MODULE"
        if [ -L "$TARGET" ] && [ ! -e "$TARGET" ]; then
            rm "$TARGET"
        fi
        if [ -L "$TARGET" ]; then
            if [ "$(readlink -f "$TARGET")" != "$SOURCE" ]; then
                echo "$NAME: refusing to replace another link: $TARGET" >&2
                exit 1
            fi
        elif [ -e "$TARGET" ]; then
            echo "$NAME: refusing to replace $TARGET" >&2
            exit 1
        else
            ln -s "$SOURCE" "$TARGET"
        fi
        linked=$((linked + 1))
    done
    if [ "$linked" -eq 0 ]; then
        echo "$NAME: no Klipper extras directory found" >&2
        exit 1
    fi
    echo "$NAME: print hooks linked into Klipper ($linked)"

    # Moonraker runs in Zmod's chroot (unless /ZMOD says there is none)
    if [ -n "${MOD:-}" ] && [ -d "$MOD" ]; then
        unset LD_LIBRARY_PATH LD_PRELOAD
        exec chroot "$MOD" /bin/sh -c \
            "ZMOD_PUSHRAKER_CHROOT=1 $CHROOT_PLUGIN_DIR/install.sh"
    fi
fi

# ---- chroot: Moonraker -----------------------------------------------------
# Zmod 1.7+ keeps Moonraker in $DATA/zmod/moonraker, older ones in
# config/base/moonraker.
MOON_DIR=
for dir in ${DATA:+"$DATA/zmod/moonraker"} /usr/data/zmod/moonraker \
    /data/zmod/moonraker /root/printer_data/config/base/moonraker \
    "$CONFIG_DIR/base/moonraker"; do
    if [ -d "$dir/components" ]; then
        MOON_DIR=$dir
        break
    fi
done
if [ -z "$MOON_DIR" ]; then
    echo "$NAME: Zmod's Moonraker not found" >&2
    exit 1
fi

for COMP in pushraker pushraker_cards; do
    TARGET="$MOON_DIR/components/$COMP.py"
    if [ -e "$TARGET" ] && [ ! -L "$TARGET" ]; then
        echo "$NAME: refusing to replace $TARGET (pip-installed pushraker?" \
            "run 'python -m pushraker uninstall' first)" >&2
        exit 1
    fi
    ln -sfn "$CHROOT_PLUGIN_DIR/moonraker/$COMP.py" "$TARGET"
    # Keep Moonraker's update manager from reporting the link as an
    # untracked file in the moonraker repo
    if [ -d "$MOON_DIR/.git" ]; then
        EXCLUDE="$MOON_DIR/.git/info/exclude"
        mkdir -p "$MOON_DIR/.git/info"
        touch "$EXCLUDE"
        grep -qxF "/components/$COMP.py" "$EXCLUDE" ||
            echo "/components/$COMP.py" >>"$EXCLUDE"
    fi
done

INC="[include plugins/$NAME/$NAME.moonraker.conf]"
FILE="$CONFIG_DIR/mod_data/plugins.moonraker.conf"
touch "$FILE"
grep -qF "$INC" "$FILE" || echo "$INC" >>"$FILE"

# Compile now: the printer takes ~25 s to compile pushraker at Moonraker's
# first start otherwise
PY=/root/moonraker-env/bin/python3
[ -x "$PY" ] || PY=python3
"$PY" -m compileall -q "$CHROOT_PLUGIN_DIR/python" "$CHROOT_PLUGIN_DIR/moonraker" \
    >/dev/null 2>&1 || true

if grep -q "plugins/notify/" "$FILE" 2>/dev/null; then
    echo "$NAME: Zmod's notify plugin is on too: DISABLE_PLUGIN name=notify" \
        "(both would send, and both define _NOTIFY)"
fi

PUSHRAKER_WEB_CHROOT=1 /bin/sh "$CHROOT_PLUGIN_DIR/web.sh" start || true

echo "$NAME installed; settings page: http://<printer>:82/notifications/"
echo "REBOOT" >/tmp/printer
