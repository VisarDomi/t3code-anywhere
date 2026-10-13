#!/bin/sh
# Builds Tailscale's open-source daemon on a Mac and installs it as a LaunchDaemon:
# no GUI, no system-extension or VPN approval on the Mac's screen, runs before login.
# Use it when nobody can click through the Tailscale app's prompts (setting a Mac up
# over SSH, or a Mac that should be reachable before anyone logs in). Otherwise the
# Standalone Tailscale app (with its CLI installed) is simpler. Needs Xcode's command
# line tools; Go is downloaded into a temporary folder. Uses sudo. Then:
#   sh macos/install.sh                      # adds KeepAlive to the daemon
#   /usr/local/bin/tailscale up --hostname=<name>   (login URL, or --auth-key=file:<path>)
set -eu
b=$(mktemp -d /tmp/tsbuild.XXXX)
# Go's module cache is read-only; unlock it so the folder can be removed.
trap 'chmod -R u+w "$b" 2>/dev/null; rm -rf "$b"' EXIT

ts=$(curl -fsSL "https://pkgs.tailscale.com/stable/?mode=json" |
    /usr/bin/python3 -c 'import json, sys; print(json.load(sys.stdin)["TarballsVersion"])')
case $(uname -m) in x86_64) goarch=amd64 ;; arm64) goarch=arm64 ;; *) exit 1 ;; esac
curl -fsSL "https://go.dev/dl/?mode=json" | /usr/bin/python3 -c '
import json, sys
f = next(f for f in json.load(sys.stdin)[0]["files"]
         if f["os"] == "darwin" and f["arch"] == sys.argv[1] and f["kind"] == "archive")
print(f["filename"], f["sha256"])' "$goarch" > "$b/go.txt"
read -r gofile gosum < "$b/go.txt"
curl -fsSL -o "$b/go.tgz" "https://go.dev/dl/$gofile"
echo "$gosum  $b/go.tgz" | shasum -a 256 -c - >/dev/null
tar -xzf "$b/go.tgz" -C "$b"

echo "Building Tailscale $ts with $gofile"
export GOROOT="$b/go" GOPATH="$b/gopath" GOCACHE="$b/cache" GOBIN="$b/bin" GOTOOLCHAIN=local
# Without the version stamps, `tailscale version` reports "<version>-ERR-BuildInfo".
"$b/go/bin/go" install \
    -ldflags "-X tailscale.com/version.longStamp=$ts -X tailscale.com/version.shortStamp=$ts" \
    "tailscale.com/cmd/tailscale@v$ts" "tailscale.com/cmd/tailscaled@v$ts"

sudo install -d -o root -g wheel -m 755 /usr/local/bin
sudo "$b/bin/tailscaled" install-system-daemon      # /usr/local/bin/tailscaled + LaunchDaemon
sudo install -o root -g wheel -m 755 "$b/bin/tailscale" /usr/local/bin/tailscale
for _ in $(seq 30); do [ -S /var/run/tailscaled.socket ] && break; sleep 0.5; done
# The logged-in user may then run `tailscale up` and `tailscale serve` (T3's Tailscale
# HTTPS setting) without sudo.
sudo /usr/local/bin/tailscale set --operator="$(id -un)"
/usr/local/bin/tailscale version | head -1
