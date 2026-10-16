# t3code-anywhere

Use [T3 Code](https://github.com/pingdotgg/t3code) on all your machines as one setup:
from your desktop, drive agents on your laptop; from the laptop, drive the desktop, at
home or from a coffee shop; from your phone, drive both. It runs over your own private
[Tailscale](https://tailscale.com) network, so nothing is opened to the internet or to
the Wi-Fi you happen to be on.

It also keeps T3 Code running: it starts at login, comes back after a crash and updates
without passwords. At home the phone uses saved LAN routes with Tailscale **off**.
At coffee, turn Tailscale **on** to reach the home desktop and the laptop, whether
it stayed home or came along. Fixed home routes survive travel; the laptop stays
closed to coffee-shop Wi-Fi. The computers keep Tailscale available in the
background for remote access. See [home and coffee connections](ROAMING.md).

## How to use it

Give your coding agent (Claude Code, Codex, or one inside T3 Code) this repository and
say:

> Set up T3 Code on my machines with https://github.com/VisarDomi/t3code-anywhere —
> follow its AGENTS.md.

It asks you a few questions first (which machines, which travel, stable or nightly)
and does the rest. What it cannot do for you:

- sign in to Tailscale (or create a short-lived token for it),
- type your password for one `sudo` command on each Linux machine,
- approve the Tailscale app's prompts on a Mac (unless it builds Tailscale from source),
- sign in to Claude, Codex or other providers in T3 Code,
- scan a QR code with your phone.

Linux and macOS, Intel and Apple silicon. Windows gets the core setup (Tailscale HTTPS
and pairing) without the helper scripts.

## What is here

| | |
| --- | --- |
| [AGENTS.md](AGENTS.md) | The runbook the agent follows |
| [ROAMING.md](ROAMING.md) | Phone VPN off at home/on at coffee, permanent LAN routes, and recovery from stale routes |
| [t3code-keepalive](t3code-keepalive) | Starts T3 at login, restarts it after a crash, finishes its Tailscale HTTPS after an offline boot |
| [linux/](linux) | `install-root.sh` (once, with sudo) and `install.sh` (T3 Code AppImage, menu entry, watcher) |
| [macos/](macos) | `install.sh` (watcher; for laptops, LAN access and a fixed address only at home) and `build-tailscaled.sh` |
| [tools/](tools) | Tailscale admin through its API, pairing without a screen, Linux keyring without a password |
