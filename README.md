# t3code-anywhere

An agent-readable runbook and small helper scripts for connecting
[T3 Code](https://github.com/pingdotgg/t3code) on your computers and phone through
your own private [Tailscale](https://tailscale.com) network. No public port forwarding
is needed. Each computer keeps its own projects, provider logins and agents.

The helpers start T3 at login, recover after a crash, and repair its Tailscale HTTPS
mapping after an offline boot. On a travelling Mac, the optional home-network helper
allows T3 on the home LAN and blocks its port on foreign Wi-Fi.

The Linux AppImage helper also repairs restart continuation on compatible T3 builds:
the desktop opens while offline, but interrupted cloud-agent turns wait for working
internet without a deadline. Codex continuations send exactly `continue`, avoiding
the affected release's `EmptyInput` failure. See [power recovery](#power-recovery-on-linux).

## Give this to your agent

Share this prompt with your coding agent:

> Set up T3 Code on my machines with https://github.com/VisarDomi/t3code-anywhere —
> follow its AGENTS.md.

The agent asks which machines you have, which travel, your release track, and whether
you want local access without the phone VPN. It uses your own device names, addresses
and account; no configuration from the author's machines is required.

To read or run the guide locally:

```sh
git clone https://github.com/VisarDomi/t3code-anywhere.git
cd t3code-anywhere
```

Start with [AGENTS.md](AGENTS.md). The scripts are individual setup steps, not a
single installer to run blindly. Some steps use `sudo`; the guide identifies them.

What the owner still does:

- sign in to Tailscale (or create a short-lived token for it),
- type your password for one `sudo` command on each Linux machine,
- approve the Tailscale app's prompts on a Mac (unless it builds Tailscale from source),
- sign in to Claude, Codex or other providers in T3 Code,
- scan pairing QR codes with the phone and verify its connections.

## Choose your phone workflow

The [home/coffee profile](ROAMING.md) uses the phone's Tailscale **off at home, on
away from home**. Explicitly saved home LAN routes survive laptop travel; the
HTTPS routes handle remote access. The computers keep Tailscale available in the
background. It covers everyone home, phone away alone, or phone and laptop away.

If your devices move independently or you prefer Tailscale-only access, tell the
agent before setup. Phone home / laptop away with the phone VPN off needs a
different connection path; the home/coffee profile does not provide a relay.

## Requirements and scope

- Linux desktop or macOS with a logged-in desktop session for the desktop helpers.
  Linux without a desktop uses T3's own background service, described in the runbook.
- Tailscale on one account and compatible T3 versions across devices. The guide
  defaults to stable; nightly requires the matching mobile beta.
- Shell, `curl` and Python 3 for the helper scripts. Some steps also use Git,
  OpenSSL, GNOME keyring tools or Python's `qrcode` module, as described in the guide.
- Linux AppImage repair uses `mksquashfs` from `squashfs-tools`; the root installer
  installs it on Debian/Ubuntu. Other distributions need that package installed first.
- macOS Intel and Apple silicon are covered. Windows uses T3 and Tailscale's native
  installers; this repository does not include Windows helper scripts.

Keep tokens, pairing links, QR codes and machine-specific configuration outside the
checkout. The repository's ignore rules are an additional safeguard. T3 UI and CLI
details can change; [ROAMING.md](ROAMING.md) links the source version used to verify
saved-route behavior.

## Power recovery on Linux

Run the normal Linux installer to install the repair and watcher. On the next app
launch, eligible interrupted turns stay in T3's durable recovery queue until one
of two HTTPS connectivity probes returns its expected empty response. Checks time
out after five seconds and retry every 30 seconds, with no overall deadline. A
router, DNS service or system clock that recovers several minutes after the PC
therefore does not consume the agent's ordinary startup attempts. Desktop/LAN access
starts independently. A captive portal is not counted as working internet.

Once online, T3 rechecks the thread and uses its existing continuation dispatch:
Stop, newer work, archived/settled threads and approval/secret requirements still
apply. Authentication, quota and ordinary provider failures retain their normal
handling. This repairs boot/restart recovery; it does not change retry policy for
arbitrary failures in a running turn. The automatic continuation input is `continue`.

This is a local AppImage repair, verified against
`0.1.7-nightly.20261101.4016`, rather than an upstream release. All changed bundle
anchors must match exactly; otherwise the helper leaves the app untouched and
records the refusal. The original AppImage, hashes and installation record are in
`~/.local/share/t3code-power-recovery/`. ASAR file offsets and SHA-256 integrity
metadata are rebuilt, and the replacement app is verified before an atomic swap.
An already running app keeps its old mounted inode until its next normal launch.

The watcher checks replacement downloads once a minute and repairs compatible
ones for their next launch. It also checks immediately before a launch it owns.
An upstream packaging change may require updating these anchors; see
`watcher.log`, `last-build.log` and `failed.json` in the repair directory. A refusal
does not prevent the original app from opening. This helper does not modify a
signed macOS app or a headless T3 installation.

Check the installed app:

```sh
python3 ~/.local/lib/t3code-power-recovery/power-recovery.py --status
```

`currentAppMatches` must be true. To undo the repair, first move
`~/.local/lib/t3code-power-recovery/` aside so the watcher no longer reapplies it,
then copy the original named by `backup` to a temporary sibling of the AppImage
and rename that file over it. The change takes effect at the next normal launch.
Do not overwrite a mounted AppImage in place or restart T3 while agents are working.

## What is here

| | |
| --- | --- |
| [AGENTS.md](AGENTS.md) | The runbook the agent follows |
| [ROAMING.md](ROAMING.md) | Phone VPN off at home/on at coffee, permanent LAN routes, and recovery from stale routes |
| [t3code-keepalive](t3code-keepalive) | Starts T3 at login, restarts it after a crash, finishes its Tailscale HTTPS after an offline boot |
| [linux/](linux) | `install-root.sh` (once, with sudo) and `install.sh` (T3 Code AppImage, menu entry, watcher) |
| [macos/](macos) | `install.sh` (watcher; for laptops, LAN access and a fixed address only at home) and `build-tailscaled.sh` |
| [tools/](tools) | Tailscale admin through its API, pairing without a screen, Linux keyring without a password |

## License

[MIT](LICENSE). This is a community setup guide, not the T3 Code or Tailscale project.
