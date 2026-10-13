#!/bin/sh
# macOS setup, as the logged-in user (uses sudo). Safe to run again.
#   sh macos/install.sh                      # t3code-keepalive LaunchAgent
#   sh macos/install.sh --wifi-home-address  # also: fixed Wi-Fi address only at home
#                                            # (run at home, with the fixed address set)
# Also gives a tailscaled built from source (macos/build-tailscaled.sh) KeepAlive.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
uid=$(id -u)
wifi=no
for arg in "$@"; do
    case $arg in
        --wifi-home-address) wifi=yes ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

# bootout returns before the job has stopped; bootstrapping too early fails.
bootout() {
    sudo launchctl bootout "$1" 2>/dev/null || return 0
    for _ in $(seq 20); do sudo launchctl print "$1" >/dev/null 2>&1 || return 0; sleep 0.5; done
}
# install_job DOMAIN LABEL PLIST-CONTENT DESTINATION OWNER
install_job() {
    tmp=$(mktemp)
    printf '%s\n' "$3" > "$tmp"
    if ! sudo cmp -s "$tmp" "$4"; then
        bootout "$1/$2"
        sudo install -o "$5" -m 644 "$tmp" "$4"
    fi
    rm -f "$tmp"
    sudo launchctl print "$1/$2" >/dev/null 2>&1 || sudo launchctl bootstrap "$1" "$4"
}

sudo install -d -o root -g wheel -m 755 /usr/local/libexec /usr/local/etc
sudo install -o root -g wheel -m 755 "$here/../t3code-keepalive" /usr/local/libexec/t3code-keepalive

# The watcher: starts T3 Code at login, relaunches it after a crash or kill.
mkdir -p "$HOME/Library/LaunchAgents"
install_job "gui/$uid" local.t3code-keepalive "<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\">
<dict>
  <key>Label</key><string>local.t3code-keepalive</string>
  <key>ProgramArguments</key><array><string>/usr/local/libexec/t3code-keepalive</string></array>
  <key>AssociatedBundleIdentifiers</key><string>com.t3tools.t3code</string>
  <key>LimitLoadToSessionType</key><string>Aqua</string>
  <key>ProcessType</key><string>Interactive</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>" "$HOME/Library/LaunchAgents/local.t3code-keepalive.plist" "$(id -un)"
# Run the copy just installed (T3 itself is not touched).
sudo launchctl kickstart -k "gui/$uid/local.t3code-keepalive"

# A tailscaled built from source: `tailscaled install-system-daemon` writes its plist
# without KeepAlive. (The Tailscale app does not use this job.)
if [ -x /usr/local/bin/tailscaled ] && [ -f /Library/LaunchDaemons/com.tailscale.tailscaled.plist ]; then
    install_job system com.tailscale.tailscaled '<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.tailscale.tailscaled</string>
  <key>ProgramArguments</key><array><string>/usr/local/bin/tailscaled</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>' /Library/LaunchDaemons/com.tailscale.tailscaled.plist root
fi

if [ "$wifi" = yes ]; then
    iface=$(networksetup -listallhardwareports | awk '/^Hardware Port: Wi-Fi$/ {getline; print $2}')
    service=$(networksetup -listnetworkserviceorder |
        awk -v dev="$iface" '/^\([0-9*]+\) / {sub(/^\([0-9*]+\) /, ""); name=$0}
                             index($0, "Device: " dev ")") {print name; exit}')
    info=$(networksetup -getinfo "$service")
    home_ip=$(printf '%s\n' "$info" | sed -n 's/^IP address: //p' | head -1)
    router=$(netstat -rn -f inet | awk -v i="$iface" '$1 == "default" && $NF == i {print $2; exit}')
    [ -n "$router" ] || router=$(ipconfig getoption "$iface" router 2>/dev/null || true)
    ping -c 1 -t 1 -b "$iface" "$router" >/dev/null 2>&1 || true
    router_mac=$(arp -n -i "$iface" "$router" 2>/dev/null | awk '$3 == "at" {print $4}')
    case "$(printf '%s\n' "$info" | head -1)" in
        Manual*) ;;
        *) echo "The Wi-Fi service \"$service\" has no fixed address; nothing to do." >&2; exit 1 ;;
    esac
    [ -n "$iface" ] && [ -n "$home_ip" ] && [ -n "$router" ] && [ -n "$router_mac" ] ||
        { echo "Could not read the home network (on Wi-Fi at home?): iface=$iface ip=$home_ip router=$router mac=$router_mac" >&2; exit 1; }
    printf 'SERVICE="%s"\nIFACE=%s\nHOME_IP=%s\nROUTER=%s\nROUTER_MAC=%s\n' \
        "$service" "$iface" "$home_ip" "$router" "$router_mac" |
        sudo tee /usr/local/etc/wifi-home-address.conf >/dev/null
    sudo install -o root -g wheel -m 755 "$here/wifi-home-address" /usr/local/libexec/wifi-home-address
    install_job system local.wifi-home-address '<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>local.wifi-home-address</string>
  <key>ProgramArguments</key><array><string>/usr/local/libexec/wifi-home-address</string></array>
  <key>StartInterval</key><integer>10</integer>
  <key>RunAtLoad</key><true/>
</dict>
</plist>' /Library/LaunchDaemons/local.wifi-home-address.plist root
    echo "Wi-Fi: $service ($iface) keeps $home_ip at home (router $router, $router_mac), DHCP elsewhere."
fi

for job in "gui/$uid/local.t3code-keepalive" system/com.tailscale.tailscaled system/local.wifi-home-address; do
    sudo launchctl print "$job" >/dev/null 2>&1 || continue
    printf '%s: ' "$job"
    sudo launchctl print "$job" | awk '/^\tstate = /{s=$3} END{print s}'
done
