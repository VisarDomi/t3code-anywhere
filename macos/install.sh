#!/bin/sh
# macOS setup, as the logged-in user (uses sudo). Safe to run again.
#   sh macos/install.sh                 # t3code-keepalive LaunchAgent
#   sh macos/install.sh --home-network  # also, for a laptop (run at home): T3 reachable on
#                                       # the LAN only at home, and a fixed home Wi-Fi
#                                       # address kept only at home (see macos/home-network)
# Also gives a tailscaled built from source (macos/build-tailscaled.sh) KeepAlive.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
uid=$(id -u)
home_network=no
for arg in "$@"; do
    case $arg in
        --home-network) home_network=yes ;;
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

if [ "$home_network" = yes ]; then
    # The router of the network the Mac is on now, which must be home.
    router=$(route -n get default 2>/dev/null | awk '/gateway:/ {print $2}')
    ping -c 1 -t 1 "$router" >/dev/null 2>&1 || true
    router_mac=$(arp -an | awk -v r="($router)" '$2 == r && $3 == "at" {print $4; exit}')
    [ -n "$router" ] && [ -n "$router_mac" ] ||
        { echo "Could not read the home router (connected at home?): router=$router mac=$router_mac" >&2; exit 1; }
    conf="ROUTER=$router
ROUTER_MAC=$router_mac
T3_LAN=yes"
    # A fixed address on the Wi-Fi service: keep it only at home.
    iface=$(networksetup -listallhardwareports | awk '/^Hardware Port: Wi-Fi$/ {getline; print $2}')
    service=$(networksetup -listnetworkserviceorder |
        awk -v dev="$iface" '/^\([0-9*]+\) / {sub(/^\([0-9*]+\) /, ""); name=$0}
                             index($0, "Device: " dev ")") {print name; exit}')
    info=$( [ -n "$service" ] && networksetup -getinfo "$service" || true)
    case "$(printf '%s\n' "$info" | head -1)" in
        Manual*)
            home_ip=$(printf '%s\n' "$info" | sed -n 's/^IP address: //p' | head -1)
            conf="$conf
SERVICE=\"$service\"
IFACE=$iface
HOME_IP=$home_ip" ;;
    esac
    printf '%s\n' "$conf" | sudo tee /usr/local/etc/home-network.conf >/dev/null
    sudo install -o root -g wheel -m 755 "$here/home-network" /usr/local/libexec/home-network
    install_job system local.home-network '<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>local.home-network</string>
  <key>ProgramArguments</key><array><string>/usr/local/libexec/home-network</string></array>
  <key>StartInterval</key><integer>10</integer>
  <key>RunAtLoad</key><true/>
</dict>
</plist>' /Library/LaunchDaemons/local.home-network.plist root
    echo "Home network: router $router ($router_mac); T3 reachable on the LAN only at home$(
        [ -n "${home_ip:-}" ] && echo "; Wi-Fi $service ($iface) fixed at $home_ip only at home")."
fi

for job in "gui/$uid/local.t3code-keepalive" system/com.tailscale.tailscaled system/local.home-network; do
    sudo launchctl print "$job" >/dev/null 2>&1 || continue
    printf '%s: ' "$job"
    sudo launchctl print "$job" | awk '/^\tstate = /{s=$3} END{print s}'
done
