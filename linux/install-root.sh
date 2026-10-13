#!/usr/bin/env bash
# Root part of the Linux setup. Run once: sudo bash linux/install-root.sh
# Safe to run again. Everything else (linux/install.sh, `tailscale up`, pairing) runs as
# the desktop user.
#   - Tailscale (official installer), with the desktop user as operator, so `tailscale up`
#     and `tailscale serve` (T3's Tailscale HTTPS setting) need no sudo
#   - ufw, when active, lets tailnet traffic in
#   - removes the T3 Code .deb if installed: the AppImage (linux/install.sh) updates
#     itself without a password; the .deb asks for one on every update
#   - GitHub CLI from GitHub's repository when gh is missing or older than T3 needs
#     (2.81), on Debian and Ubuntu
set -euo pipefail

user="${SUDO_USER:?run this with sudo from the desktop user}"

if ! command -v tailscale >/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
systemctl enable --now tailscaled
for _ in $(seq 40); do [ -S /var/run/tailscale/tailscaled.sock ] && break; sleep 0.5; done
tailscale set --operator="$user"
echo "Tailscale $(tailscale version | head -1); operator: $user"

if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q '^Status: active'; then
  ufw allow in on tailscale0 comment 'tailnet'
fi

if command -v dpkg-query >/dev/null &&
   dpkg-query -W -f '${Status}' t3code 2>/dev/null | grep -q "install ok installed"; then
  apt-get remove -y -q t3code
fi

gh_ok() {
  command -v gh >/dev/null || return 1
  IFS=. read -r major minor _ < <(gh --version | sed -n 's/^gh version \([0-9.]*\).*/\1/p')
  [ "${major:-0}" -gt 2 ] || { [ "${major:-0}" -eq 2 ] && [ "${minor:-0}" -ge 81 ]; }
}
if ! gh_ok && command -v apt-get >/dev/null; then
  install -d -m 755 /etc/apt/keyrings
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    -o /etc/apt/keyrings/githubcli-archive-keyring.gpg
  chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list
  apt-get update -q
  apt-get install -y -q gh
fi
command -v gh >/dev/null && gh --version | head -1
gh_ok || echo "Note: gh is missing or older than 2.81; T3's GitHub features need a newer one."
