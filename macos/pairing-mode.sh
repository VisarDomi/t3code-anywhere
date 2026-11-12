#!/bin/sh
# Run on the Mac. Pairing mode: while it is on, a device paired with a pairing link gets a
# 100-year session instead of 30 days (paired-sessions.mjs). T3 honours the expiry it
# signed, so those devices stay signed in on the normal, unmodified app afterwards.
#
#   sh macos/pairing-mode.sh on     # quit T3 Code first (Cmd+Q)
#   ...create pairing links and pair the devices...
#   sh macos/pairing-mode.sh off    # back to the normal app
#
# The signed app is not modified: its own binary runs the server through t3-server.mjs on
# the same data and port. The job is not a login item, so restarting the Mac also ends
# pairing mode. Threads running on the Mac are interrupted at "on" and again at "off".
set -eu
here=$(cd "$(dirname "$0")" && pwd)
label=local.t3code-pairing
domain="gui/$(id -u)"
state="$HOME/.local/share/t3code-pairing"
keepalive="$HOME/Library/LaunchAgents/local.t3code-keepalive.plist"
app="${T3_APP:-/Applications/T3 Code (Nightly).app}"
name=$(basename "$app" .app)

# bootout returns before the job is gone; bootstrap fails while it still exists.
gone() {
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do
        launchctl print "$domain/$1" >/dev/null 2>&1 || return 0
        sleep 1
    done
    return 1
}

off() {
    launchctl bootout "$domain/$label" 2>/dev/null || true
    gone "$label" || { echo "the pairing server did not stop" >&2; exit 1; }
    rm -rf "$state"
    [ ! -f "$keepalive" ] || launchctl bootstrap "$domain" "$keepalive" 2>/dev/null || true
    open -g -b com.t3tools.t3code
}

case "${1:-}" in
on)
    [ -x "$app/Contents/MacOS/$name" ] || { echo "no T3 app at $app" >&2; exit 1; }
    if lsappinfo info -only pid -app com.t3tools.t3code 2>/dev/null | grep -q '"pid"='; then
        echo "Quit T3 Code first (Cmd+Q), then run this again." >&2
        exit 1
    fi
    install -d -m 700 "$state"
    install -m 644 "$here/paired-sessions.mjs" "$here/t3-server.mjs" "$state/"
    # The keepalive would reopen the app, and the app refuses to start while another
    # server owns its data folder.
    launchctl bootout "$domain/local.t3code-keepalive" 2>/dev/null || true
    # Provider CLIs and terminals need the login shell's PATH, not launchd's minimal one.
    path=$(/bin/zsh -lic 'print -r -- "$PATH"' 2>/dev/null </dev/null | tail -n 1)
    [ -n "$path" ] || path=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
    /usr/bin/python3 - "$state/$label.plist" "$app" "$name" "$state" "$path" "$HOME" "$label" <<'PY'
import plistlib, sys
plist, app, name, state, path, home, label = sys.argv[1:]
with open(plist, "wb") as handle:
    plistlib.dump({
        "Label": label,
        "ProgramArguments": [f"{app}/Contents/MacOS/{name}", f"{state}/t3-server.mjs",
                             "serve", "--mode", "web", "--host", "0.0.0.0", "--port", "3773", "--no-browser"],
        "EnvironmentVariables": {"ELECTRON_RUN_AS_NODE": "1", "T3CODE_HOME": f"{home}/.t3", "T3_ANYWHERE_APP": app,
                                 "T3_ANYWHERE_STATUS": f"{state}/status.json", "PATH": path, "LANG": "en_US.UTF-8"},
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 15,
        "ProcessType": "Interactive",
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": f"{state}/server.log",
    }, handle)
PY
    launchctl bootout "$domain/$label" 2>/dev/null || true
    gone "$label" || { echo "an earlier pairing server did not stop" >&2; exit 1; }
    launchctl bootstrap "$domain" "$state/$label.plist"
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do
        if grep -q '"state": "patched"' "$state/status.json" 2>/dev/null &&
            curl -sf -m 2 http://127.0.0.1:3773/.well-known/t3/environment >/dev/null; then
            echo "pairing mode is on: pair the devices, then run: sh $0 off"
            exit 0
        fi
        sleep 2
    done
    echo "pairing mode did not start (this T3 version may have changed its session code):" >&2
    cat "$state/status.json" >&2 2>/dev/null || true
    off
    echo "switched back to the normal app; devices paired now would get 30 days" >&2
    exit 1
    ;;
off)
    off
    echo "pairing mode is off; T3 Code is starting normally"
    ;;
*)
    sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
