#!/bin/sh
# Run on the Mac. Installs its T3 Code server as a LaunchAgent (local.t3code-server)
# with paired-device sessions that never expire; see t3-server.mjs. Idempotent.
#
# The service waits while the desktop app's own server owns ~/.t3, so it can be
# installed first: switching off Local environment in the desktop app (Settings ->
# Environments) hands the data folder over within 15 seconds. Undo: run with
# --uninstall, then switch Local environment back on.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
label=local.t3code-server
plist="$HOME/Library/LaunchAgents/$label.plist"
lib="$HOME/.local/lib/t3code-server"
domain="gui/$(id -u)"

if [ "${1:-}" = --uninstall ]; then
    launchctl bootout "$domain/$label" 2>/dev/null || true
    rm -f "$plist"
    echo "removed $label; switch Local environment back on in the desktop app"
    exit 0
fi

app="${T3_APP:-/Applications/T3 Code (Nightly).app}"
name=$(basename "$app" .app)
[ -x "$app/Contents/MacOS/$name" ] || { echo "no T3 app at $app" >&2; exit 1; }
install -d -m 700 "$lib" "$HOME/.local/share/t3code-server"
install -m 644 "$here/paired-sessions.mjs" "$here/t3-server.mjs" "$lib/"
# Provider CLIs and terminals need the login shell's PATH, not launchd's minimal one.
path=$(/bin/zsh -lic 'print -r -- "$PATH"' 2>/dev/null </dev/null | tail -n 1)
[ -n "$path" ] || path=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin

/usr/bin/python3 - "$plist" "$app" "$name" "$lib" "$path" "$HOME" <<'EOF'
import os, plistlib, sys
plist, app, name, lib, path, home = sys.argv[1:]
data = {
    "Label": "local.t3code-server",
    "ProgramArguments": [f"{app}/Contents/MacOS/{name}", f"{lib}/t3-server.mjs",
                         "serve", "--mode", "web", "--host", "0.0.0.0", "--port", "3773", "--no-browser"],
    "EnvironmentVariables": {"ELECTRON_RUN_AS_NODE": "1", "T3CODE_HOME": f"{home}/.t3", "T3_ANYWHERE_APP": app,
                             "PATH": path, "LANG": "en_US.UTF-8"},
    "RunAtLoad": True,
    "KeepAlive": True,
    "ThrottleInterval": 15,
    "ProcessType": "Interactive",
    "StandardOutPath": "/dev/null",
    "StandardErrorPath": f"{home}/Library/Logs/t3code-server.log",
}
os.makedirs(os.path.dirname(plist), exist_ok=True)
with open(plist + ".tmp", "wb") as handle:
    plistlib.dump(data, handle)
os.replace(plist + ".tmp", plist)
EOF

launchctl bootout "$domain/$label" 2>/dev/null || true
# bootout returns before the job is gone; bootstrap fails while it still exists.
for _ in 1 2 3 4 5 6 7 8 9 10; do launchctl print "$domain/$label" >/dev/null 2>&1 || break; sleep 1; done
launchctl bootstrap "$domain" "$plist"
echo "installed $label; status: ~/.local/share/t3code-server/status.json"
