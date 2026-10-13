#!/bin/sh
# User part of the Linux setup. Run as the desktop user (after linux/install-root.sh):
#   T3_TRACK=stable sh linux/install.sh      # or T3_TRACK=nightly; same track everywhere
# Safe to run again.
#   - T3 Code AppImage at ~/Applications/T3-Code.AppImage. It updates itself in place
#     without a password (the .deb asks for one on every update, and an update started
#     from another machine would hang on that prompt). The file name must not contain a
#     version, or updates write a new file next to it.
#   - menu entry, icon and t3code:// handler (sign-in callbacks) from the AppImage
#   - T3's own `t3` command in ~/.local/bin (what About → t3 command → Install does)
#   - t3code-keepalive in ~/.local/bin, started at login (XDG autostart) and now
set -eu
here=$(cd "$(dirname "$0")" && pwd)
track=${T3_TRACK:-stable}
app=$HOME/Applications/T3-Code.AppImage
repo=https://github.com/pingdotgg/t3code

if [ ! -x "$app" ]; then
    case $track in
        stable)
            tag=$(curl -fsSL https://api.github.com/repos/pingdotgg/t3code/releases/latest |
                python3 -I -c 'import json, sys; print(json.load(sys.stdin)["tag_name"])')
            feed=latest-linux.yml ;;
        nightly)
            tag=$(curl -fsSL "https://api.github.com/repos/pingdotgg/t3code/releases?per_page=30" |
                python3 -I -c 'import json, sys; print(next(r["tag_name"] for r in json.load(sys.stdin) if "nightly" in r["tag_name"]))')
            feed=nightly-linux.yml ;;
        *) echo "T3_TRACK must be stable or nightly" >&2; exit 1 ;;
    esac
    arch=$(uname -m)   # x86_64 or aarch64 → the feed names arm64 AppImages "arm64"
    [ "$arch" = aarch64 ] && { arch=arm64; feed=${feed%.yml}-arm64.yml; }
    tmp=$(mktemp -d)
    curl -fsSL -o "$tmp/feed.yml" "$repo/releases/download/$tag/$feed"
    file=$(sed -n "s/^  - url: \(.*-$arch\.AppImage\)$/\1/p" "$tmp/feed.yml")
    want=$(sed -n "/url: $file/{n;s/^ *sha512: //p}" "$tmp/feed.yml")
    [ -n "$file" ] && [ -n "$want" ] || { echo "no $arch AppImage in $tag/$feed" >&2; exit 1; }
    echo "Downloading $file ($tag)"
    curl -fsSL -o "$tmp/app" "$repo/releases/download/$tag/$file"
    [ "$(openssl dgst -sha512 -binary "$tmp/app" | base64 | tr -d '\n')" = "$want" ] ||
        { echo "$file does not match the sha512 in $feed" >&2; exit 1; }
    install -d "$HOME/Applications"
    install -m 755 "$tmp/app" "$app"
    rm -rf "$tmp"
fi

# Menu entry and icon from the AppImage, pointed at its fixed path.
tmp=$(mktemp -d)
(cd "$tmp" && "$app" --appimage-extract '*.desktop' >/dev/null &&
    "$app" --appimage-extract 'usr/share/icons/*' >/dev/null)
install -d "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/512x512/apps"
install -m 644 "$tmp/squashfs-root/usr/share/icons/hicolor/512x512/apps/t3code.png" \
    "$HOME/.local/share/icons/hicolor/512x512/apps/t3code.png"
sed -e "s|^Exec=.*|Exec=$app %U|" -e '/^X-AppImage-/d' "$tmp"/squashfs-root/*.desktop \
    > "$HOME/.local/share/applications/t3code.desktop"
rm -rf "$tmp"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
xdg-mime default t3code.desktop x-scheme-handler/t3code x-scheme-handler/t3code-dev 2>/dev/null || true

install -d "$HOME/.local/bin" "$HOME/.config/autostart"
install -m 755 "$here/../t3code-keepalive" "$HOME/.local/bin/t3code-keepalive"
# T3 writes ~/.t3/bin/t3 on its first run; run this script again afterwards if missing.
[ -x "$HOME/.t3/bin/t3" ] && ln -sfn "$HOME/.t3/bin/t3" "$HOME/.local/bin/t3"
cat > "$HOME/.config/autostart/t3code-keepalive.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=T3 Code
Comment=Starts T3 Code and relaunches it after a crash or kill (t3code-anywhere)
Exec=$HOME/.local/bin/t3code-keepalive
Icon=t3code
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

# (Re)start the watcher now. A running one keeps executing its old copy; stop it first
# (T3 itself is not touched).
lock=${XDG_RUNTIME_DIR:-/tmp}/t3code-keepalive.lock
for pid in $(command -v fuser >/dev/null && fuser "$lock" 2>/dev/null); do
    grep -q t3code-keepalive "/proc/$pid/cmdline" 2>/dev/null && kill "$pid"
done
sleep 1
setsid "$HOME/.local/bin/t3code-keepalive" >/dev/null 2>&1 </dev/null &
echo "T3 Code AppImage: $app; watcher started (starts T3 if it is not running)."
