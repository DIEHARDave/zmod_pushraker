#!/bin/sh
# zmod_pushraker - run by Zmod's DISABLE_PLUGIN name=zmod_pushraker.
# Removes install.sh's links and include and stops the settings page. The
# notification settings (printer_data/config/pushraker.conf and
# printer_data/pushraker.secrets) stay, for a later reinstall.

[ -f /opt/config/mod/.shell/0.sh ] && . /opt/config/mod/.shell/0.sh
[ -f /usr/data/zmod/zmod/.shell/0.sh ] && . /usr/data/zmod/zmod/.shell/0.sh

set -u

NAME=zmod_pushraker
CHROOT_PLUGIN_DIR="/opt/config/mod_data/plugins/$NAME"
PLUGIN_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
CONFIG_DIR=$(CDPATH= cd -- "$PLUGIN_DIR/../../.." && pwd -P)

# ---- host: Klipper ---------------------------------------------------------
if [ ! -f /ZMOD ] && [ -z "${ZMOD_PUSHRAKER_CHROOT:-}" ]; then
    for EXTRAS_DIR in \
        /usr/prog/klipper/klippy/extras \
        /usr/data/zmod/klipper/klippy/extras \
        ${KLIPPER_DIR:+"$KLIPPER_DIR/klippy/extras"}
    do
        TARGET="$EXTRAS_DIR/pushraker_hooks.py"
        [ -L "$TARGET" ] || continue
        case "$(readlink "$TARGET")" in
            "$PLUGIN_DIR"/*|*/plugins/$NAME/*) rm -f "$TARGET" ;;
        esac
    done
    if [ -n "${MOD:-}" ] && [ -d "$MOD" ]; then
        unset LD_LIBRARY_PATH LD_PRELOAD
        exec chroot "$MOD" /bin/sh -c \
            "ZMOD_PUSHRAKER_CHROOT=1 $CHROOT_PLUGIN_DIR/uninstall.sh"
    fi
fi

# ---- chroot: Moonraker -----------------------------------------------------
PUSHRAKER_WEB_CHROOT=1 /bin/sh "$CHROOT_PLUGIN_DIR/web.sh" stop

FILE="$CONFIG_DIR/mod_data/plugins.moonraker.conf"
[ -f "$FILE" ] && sed -i "\|plugins/$NAME/$NAME\.moonraker\.conf|d" "$FILE"

MOON_DIR=
for dir in ${DATA:+"$DATA/zmod/moonraker"} /usr/data/zmod/moonraker \
    /data/zmod/moonraker /root/printer_data/config/base/moonraker \
    "$CONFIG_DIR/base/moonraker"; do
    if [ -d "$dir/components" ]; then
        MOON_DIR=$dir
        break
    fi
done
if [ -n "$MOON_DIR" ]; then
    for COMP in pushraker pushraker_cards; do
        TARGET="$MOON_DIR/components/$COMP.py"
        if [ -L "$TARGET" ]; then
            case "$(readlink "$TARGET")" in
                "$CHROOT_PLUGIN_DIR"/*) rm "$TARGET" ;;
            esac
        fi
        EXCLUDE="$MOON_DIR/.git/info/exclude"
        [ -f "$EXCLUDE" ] && sed -i "\|^/components/$COMP\.py\$|d" "$EXCLUDE"
    done
fi

echo "$NAME uninstalled"
echo "REBOOT" >/tmp/printer
