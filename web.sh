#!/bin/sh
# zmod_pushraker: pushraker's settings page on port 82.
#
#   web.sh start    (re)start the port 82 server
#   web.sh stop     stop it
#   web.sh status   say whether it runs
#
# Zmod writes its nginx config from a template at every start, so the page
# can't be added there. Like zmod_dualweb's port 81, this runs a second
# nginx built from Zmod's template: its port 80 server moved to port 82
# (the Moonraker, webcam and screen proxies the page uses stay the same),
# plus /notifications/ with the page from the plugin's
# python/pushraker/web.

unset LD_PRELOAD

PLUGIN=/opt/config/mod_data/plugins/zmod_pushraker

# Zmod's nginx lives inside its chroot; run there like S70httpd.
if [ ! -f /ZMOD ] && [ -z "$PUSHRAKER_WEB_CHROOT" ]; then
    . /usr/data/zmod/zmod/.shell/0.sh
    exec chroot "$MOD" /usr/bin/env PUSHRAKER_WEB_CHROOT=1 /bin/sh "$PLUGIN/web.sh" "$@"
fi

PORT=82
ZNGINX=/usr/data/zmod/zmod/.shell/root/nginx
DIR=/root/nginx/zmod_pushraker
CONF=$DIR/nginx.conf
PID_FILE=$DIR/nginx.pid
WEB=$PLUGIN/python/pushraker/web
# Zmod's S70httpd stops its server with "killall nginx". A copy of the
# binary under another name keeps port 82 up through that (busybox killall
# also matches the target of /proc/PID/exe, so a symlink is not enough).
BIN=$DIR/zpushraker
LOG=/opt/config/mod_data/log/zmod_pushraker.log

running() {
    pid=$(cat "$PID_FILE" 2>/dev/null) && kill -0 "$pid" 2>/dev/null
}

stop() {
    if running; then
        kill "$pid"
        i=0
        while kill -0 "$pid" 2>/dev/null && [ $i -lt 5 ]; do
            sleep 1
            i=$((i + 1))
        done
    fi
    killall zpushraker 2>/dev/null
    rm -f "$PID_FILE"
}

start() {
    if [ ! -x "$ZNGINX/nginx" ] || [ ! -f "$ZNGINX/nginx.conf" ]; then
        echo "pushraker web: Zmod's nginx not found in $ZNGINX" >&2
        exit 1
    fi
    if [ ! -f "$WEB/index.html" ]; then
        echo "pushraker web: no settings page in $WEB" >&2
        exit 1
    fi

    stop
    mkdir -p "$DIR/client-body" "$DIR/proxy"
    if [ -L "$BIN" ] || ! cmp -s "$ZNGINX/nginx" "$BIN"; then
        rm -f "$BIN"
        cp "$ZNGINX/nginx" "$BIN" && chmod 755 "$BIN" || exit 1
    fi

    # Keep only the port 80 server block of Zmod's template, move it to our
    # port, add the page, and give this instance its own pid and temp files.
    awk '
        /^    server \{/ { buf = $0 "\n"; depth = 1; next }
        depth > 0 {
            buf = buf $0 "\n"
            if ($0 ~ /\{/) depth++
            if ($0 ~ /\}/) depth--
            if (depth == 0 && buf ~ /listen 80;/) printf "%s", buf
            next
        }
        { print }
    ' "$ZNGINX/nginx.conf" | sed \
        -e "s|^pid .*|pid $PID_FILE;|" \
        -e "s|^error_log .*|error_log $DIR/error.log crit;|" \
        -e "s|client_body_temp_path .*|client_body_temp_path $DIR/client-body;|" \
        -e "s|proxy_temp_path .*|proxy_temp_path $DIR/proxy;|" \
        -e "s|listen 80;|listen $PORT;\\
        location /notifications/ { alias $WEB/; index index.html; add_header Cache-Control \"no-store\"; }|" \
        > "$CONF"

    if ! grep -q "listen $PORT;" "$CONF"; then
        echo "pushraker web: no port 80 server in Zmod's nginx template" >&2
        exit 1
    fi
    if ! "$BIN" -t -q -c "$CONF" -e "$LOG"; then
        echo "pushraker web: nginx rejected $CONF, see $LOG" >&2
        exit 1
    fi
    "$BIN" -c "$CONF" -e "$LOG" || exit 1
    echo "pushraker web: settings page on port $PORT (/notifications/)"
}

case "$1" in
    start|restart)
        start
        ;;
    stop)
        stop
        echo "pushraker web: port $PORT stopped"
        ;;
    status)
        if running; then
            echo "pushraker web: settings page on port $PORT (/notifications/)"
        else
            echo "pushraker web: port $PORT not running"
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|status}" >&2
        exit 1
        ;;
esac
