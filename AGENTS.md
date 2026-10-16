# T3 Code across your machines: runbook for agents

You are setting up [T3 Code](https://github.com/pingdotgg/t3code) so that the owner's
desktop apps drive agents on each other's computers, at home or away, and the T3 phone
app drives all of them. Everything travels over the owner's own Tailscale network
(tailnet); T3 is published on the tailnet only, over HTTPS, and nowhere else.

## How it works

- **Tailscale** on every device, signed in to one account, with MagicDNS and HTTPS
  certificates on. Each computer is `<name>.<tailnet>.ts.net`.
- **T3 Code desktop** on each computer, all on the same release track (stable or
  nightly: a client and a server on different protocol versions refuse each other).
  Each computer hosts its own environment: its projects, provider logins and agents.
- **T3's own settings do the networking** (Settings → Connections):
  - **Tailscale HTTPS: on.** T3 runs `tailscale serve --bg --https=443
    http://127.0.0.1:<port>` when it starts and removes it when it quits.
  - **Network access** lets devices on the same LAN connect without Tailscale: T3 then
    listens on 0.0.0.0, and clients learn each computer's LAN address as a route of
    its own, tried before Tailscale. These learned routes are temporary: T3 removes
    them when the server stops reporting them. They are shortcuts, not the roaming
    connection. Keep Tailscale connected on every device, even a phone at home,
    because the other computer may be away. On a desktop that stays home it is safe
    to leave Network access on. On a laptop it
    would also open T3 to every Wi-Fi it joins: there, either leave it off, or turn it
    on together with `macos/install.sh --home-network`, which keeps T3's port closed
    to the LAN everywhere except at home.
  - **Pairing**: each client (desktop or phone) pairs once per computer with a one-time
    link using the permanent Tailscale HTTPS name. Verify that route is saved without
    "found automatically". T3 handles reconnection while Tailscale is connected;
    automatic LAN discovery cannot reach a remote computer or start a disabled VPN.
- **[`t3code-keepalive`](t3code-keepalive)** (Linux and macOS) covers what T3 does not:
  it starts T3 at login; relaunches it when it dies without being quit (a normal Quit
  is respected); stops the backend a killed T3 leaves running (it would hold the port
  and database while a second T3 starts on the next port); and, because T3 runs
  `tailscale serve` only once, publishes T3 the same way when a computer booted before
  Tailscale was connected.
- **Linux runs the AppImage**, not the `.deb`: the AppImage updates itself without a
  password; the `.deb` asks for one on every update, and an update started from another
  machine waits on that prompt with nobody there. **macOS runs the DMG** app.

Optional pieces, each only when it applies:

| Piece | When |
| --- | --- |
| [`macos/install.sh --home-network`](macos/home-network) | A Mac laptop. Home is recognised by the router's MAC address. T3's port is reachable on the LAN only at home (the packet filter closes it elsewhere; Tailscale always passes), so Network access can stay on. A fixed home IP address, if the Wi-Fi has one, is kept only at home (macOS would apply it on every network and leave the laptop offline elsewhere); DHCP elsewhere. |
| [`macos/build-tailscaled.sh`](macos/build-tailscaled.sh) | A Mac where nobody can click the Tailscale app's prompts (set up over SSH), or that must be on the tailnet before anyone logs in. |
| [`tools/keyring-blank-password`](tools/keyring-blank-password) | A Linux desktop that logs in automatically: nothing unlocks the GNOME keyring, so T3 asks for its password after every login. |
| [`tools/tailscale-api.sh`](tools/tailscale-api.sh) | The owner prefers giving you a short-lived API token to clicking in the Tailscale admin console. |
| [`tools/add-environment.mjs`](tools/add-environment.mjs) | Pairing a desktop app without anyone at its screen. |

Windows: Tailscale's app and T3's installer give the core setup (Tailscale HTTPS,
pairing); the scripts here are for Linux and macOS.

## 1. Ask the owner first

1. Which computers? For each: operating system (Linux distribution; macOS on Intel or
   Apple silicon; Windows), a short name for the tailnet, whether it travels or stays
   home, whether it has a screen and someone at it, and how you reach it (you run on it,
   or SSH).
2. A phone or tablet? The stable track uses the App Store / Google Play app; nightly
   needs T3's beta app (Settings → General → About → Mobile app shows the links).
3. Release track: **stable** unless they want nightly. The same on every device.
4. Tailscale: existing account or a new one (free)? Will they click a few settings in
   the admin console, or give you a 1-day API access token instead?
5. Linux: can you run `sudo`, or will they run one command per computer? Does the
   computer log in automatically?
6. At home, should devices reach each other without Tailscale (for example a phone that
   temporarily disconnects Tailscale)? Then Network access goes on, and Mac laptops
   get the home-network piece. Does a laptop use a fixed IP address at home? Explain
   that this works only while both endpoints are home; automatic roaming requires
   Tailscale on the phone at home too. See [ROAMING.md](ROAMING.md).

## 2. Ground rules

- If you run inside T3 Code on one of these computers, quitting, restarting or updating
  that T3 ends your turn. Do it last, through a delayed job (Linux: `systemd-run --user
  --on-active=30s -p KillMode=process <script>`), after telling the owner; they send
  "continue".
- Never kill processes by name. Use PIDs from T3's own files:
  `~/.t3/userdata/server-runtime.json` (backend), `~/.config/t3code-v2/SingletonLock`
  (Linux desktop app; `lsappinfo` on macOS).
- API tokens, device keys and pairing links are secrets: mode-600 files outside any
  repository, never on command lines, in chat or in logs; delete them at the end and
  revoke the API token.
- T3's desktop settings are `~/.t3/userdata/desktop-settings.json`. T3 rewrites the
  whole file from memory: change settings in the app, or edit the file only while T3 is
  quit.
- Over SSH a Mac's non-interactive PATH lacks `/usr/local/bin`; call tools by full path.
  Its login keychain is locked over SSH (for example `gh auth status` fails there and
  works in the GUI session).

## 3. The tailnet

Needed: MagicDNS on (the default for new tailnets) and HTTPS certificates on.

- **Console**: admin console → DNS → MagicDNS **Enable**; HTTPS Certificates **Enable**.
  Devices then join with the login link `tailscale up` prints, or the Tailscale app.
- **API**: the owner creates an access token (Settings → Keys → Generate access token,
  1 day). Save it to `~/.config/t3code-anywhere/tailscale-api-token` (mode 600), then
  `tools/tailscale-api.sh check`, `https-on`, and `auth-key <file>` for a 1-day device
  key used as `tailscale up --auth-key=file:<file>`.

After every device has joined: `tools/tailscale-api.sh no-expiry <name>` for each
computer (or admin console → Machines → … → Disable key expiry), so they never need to
sign in again; then `tools/tailscale-api.sh revoke-token`. HTTPS certificate names
(`<name>.<tailnet>.ts.net`) are published in Certificate Transparency logs.

## 4. Each Linux computer

1. Root, once: `sudo bash linux/install-root.sh` (the owner runs it if you have no
   sudo). Tailscale with the desktop user as operator (no sudo for `tailscale up` or
   `serve`), ufw opened for `tailscale0`, any T3 `.deb` removed, `gh` ≥ 2.81 (T3's
   GitHub features) on Debian and Ubuntu.
2. `tailscale up --hostname=<name>` (add `--auth-key=file:<key>` with the API route).
   Only tailnet traffic should change: `resolvectl status` shows `tailscale0` with
   `-DefaultRoute` and just the tailnet domain (other DNS unchanged), `ip route` is
   unchanged (tailnet routes are in table 52). Anything else: `tailscale down`, report.
3. `T3_TRACK=<stable|nightly> sh linux/install.sh`: AppImage at
   `~/Applications/T3-Code.AppImage` (sha512 checked against T3's update feed), menu
   entry and `t3code://` handler, the watcher in autostart; it starts T3. The owner
   finishes T3's first-run screens (provider sign-in). Run the script again afterwards
   so it links T3's `t3` command (`~/.t3/bin/t3`, written on first run) into
   `~/.local/bin`, replacing any older `t3` there.
4. Automatic login: `python3 tools/keyring-blank-password` (the owner types the keyring
   password; explain that the keyring file is then unencrypted on disk).

A Linux computer without a screen or desktop session cannot run the desktop app. T3's
background service serves it instead (`t3 service install`: systemd user unit with
restart and lingering, updates without root); other machines pair with it like any
computer, and its Tailscale HTTPS comes from `t3 pair --tailscale` once (a persistent
mapping). The watcher and `linux/install.sh` do not apply there.

## 5. Each Mac

1. Tailscale, one of:
   - **Standalone app** from pkgs.tailscale.com: the owner approves its prompts on the
     Mac and signs in, then Settings → CLI integration → **Show me how** → **Install
     Now** (administrator password), which puts `tailscale` in `/usr/local/bin`: T3
     runs `tailscale` from the PATH. (The App Store build has no installed CLI; its
     command line is the app binary itself, which T3 does not find.)
   - **Nobody at the Mac**: `sh macos/build-tailscaled.sh`, then
     `/usr/local/bin/tailscale up --hostname=<name>`.
2. T3 Code: the DMG for the track and the Mac's architecture (x64 or arm64) from
   [GitHub Releases](https://github.com/pingdotgg/t3code/releases), or
   `brew install --cask t3-code` for stable. Compare the file with the release asset's
   `digest`, then `codesign --verify --deep --strict` and `spctl -a -t exec` on the app
   (notarized; team ARK85ZXQ4Z); copy it to `/Applications`. The owner finishes T3's
   first-run screens.
3. `sh macos/install.sh` (sudo): the watcher LaunchAgent, which starts T3, and
   KeepAlive for a source-built tailscaled. A laptop: `sh macos/install.sh
   --home-network`, run at home (it records the router, and a fixed Wi-Fi address if
   the Wi-Fi service has one).

## 6. T3 Code settings, on each computer

- Settings → Connections → **Tailscale HTTPS: on** (or `"tailscaleServeEnabled": true`
  in the settings file, with T3 quit).
- **Network access**: on where devices should meet on the home LAN without Tailscale
  (Mac laptops only together with `--home-network`); otherwise off.
- Settings → General → **Update track**: the same everywhere.
- **Continue threads after restarts**: on (the default).

Check on each computer: `tailscale serve status` shows `https://<name>.<tailnet>.ts.net`
→ `http://127.0.0.1:<port>`. From another device: `curl -s
https://<name>.<tailnet>.ts.net/.well-known/t3/environment` returns its version and
`orchestrationProtocolVersion` (the same on all; the first request after enabling waits
~20 s for the certificate).

## 7. Pairing

Links, created on the computer to be reached (single use; the default permissions are
right; create them after every computer runs its final T3 version, because a link
carries the permissions of the version that issued it):

```sh
~/.t3/bin/t3 auth pairing create --base-url https://<name>.<tailnet>.ts.net \
  --label <client> --ttl 7d --json </dev/null      # → pairUrl
```

(or Settings → Connections → **Create link**, which also shows a QR code).

- **A desktop app**: Settings → Connections → **Add environment**, the link in the Host
  field. Without anyone at the screen: [`tools/add-environment.mjs`](tools/add-environment.mjs).
- **The phone**: Tailscale on, then scan a QR code of the link in the T3 app
  (`python3 -c 'import qrcode, sys; qrcode.make(sys.argv[1]).save("pair.png")' <link>`).
  In Tailscale → profile/settings → VPN On Demand, enable it and set **Wi-Fi:
  Always** and **Cellular: Always**, with no home-network exception. Leave the VPN
  connected. Use no exit node unless the owner separately wants one. This is needed
  even at home when a paired laptop is away. Verify each computer has a saved
  `https://<name>.<tailnet>.ts.net/` route without "found automatically"; if already
  present, retain the pairing and do not replace its URL with a LAN address.

Check: `~/.t3/bin/t3 auth session list` on each computer lists its paired clients, and
`~/.t3/bin/t3 auth pairing list` is empty.

## 8. Hand over

Tell the owner, in plain words: what runs where, the steps only they did, how updates
work (below), and where this runbook is. Delete secrets and revoke the API token.

## Day to day

- **Updates** never install by themselves and need no password: Settings → General →
  About → **Download**, then **Install**; or the update button at the bottom left of
  the main sidebar (circular arrows; a labelled pill when something is out of date),
  which updates providers, then other computers, then this app. Settings → Connections
  → **Update all** updates the other computers. Keep all on one protocol version.
- **Restarts**: interrupted threads continue (Continue threads after restarts). The
  watcher restarts T3 after a crash or kill, never after Quit.
- **Away from home**: the laptop joins any Wi-Fi; Tailscale reconnects and other devices
  reach it at its tailnet name. With `--home-network`, its T3 is closed to that Wi-Fi.
- **The phone**: VPN On Demand keeps Tailscale connected on Wi-Fi and cellular,
  including home Wi-Fi. The permanent HTTPS route survives LAN changes. T3 learns
  current LAN shortcuts after connecting; learned home routes can disappear after
  a laptop travels. Do not promise that one successful home connection permanently
  teaches the phone its home addresses. See [ROAMING.md](ROAMING.md) for recovery and
  the optional setup for local access while Tailscale is deliberately disconnected.
- **New device**: Tailscale on the same account, key expiry off, pair it (step 7).
- **Phone notifications** (agent finished, needs approval) need T3 Connect (sign in,
  link the environments, enable Device Notifications in the phone app); a Tailscale
  connection alone does not deliver them.
- **Agents' browser**: T3's browser tools open tabs under a profile (`preview_status`
  lists them, `preview_open` takes `profileId`); logins live in the profile.

## Facts that trip setups up

- T3's "SSH" environments start servers only on Linux and Apple-silicon hosts; pair an
  Intel Mac directly.
- T3's Tailscale HTTPS row shows its status only with Network access or the setting on.
- `tailscaled install-system-daemon` writes a plist without KeepAlive; run
  `macos/install.sh` again after rebuilding Tailscale.
- `launchctl bootout` returns before the job has stopped; bootstrapping at once fails
  (the scripts wait).
- The Tailscale API answers `null` to successful PATCH, POST and DELETE calls; key
  descriptions accept letters, digits, spaces and hyphens only.
- A computer that sleeps is unreachable: keep hosts awake (or wake them) when other
  devices rely on them.
