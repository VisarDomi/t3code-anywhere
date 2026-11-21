# T3 Code across machines

Private Mac work backs up to VisarDomi/t3code-anywhere-private (private-backup);
public origin is upstream. Never publish private configuration/incidents.
Read README.md, ROAMING.md and the relevant linux/, macos/ or tools/ script before setup.
Discover existing hosts, pinned identities, credentials and routes before asking
the owner. Stable is default for new setups; preserve the chosen track everywhere.

## This owner's machines

T3 on the owner's machines does not use Tailscale: away from home it goes through the owner's own
relay, with sessions paired in pairing mode (README, "Pairing mode"); the values are in the private
environment repo (`t3code/README.md`, `WHERE.md`). The PC and the Mac run Tailscale for one other
purpose, remote desktop; leave it alone, never enable T3's Tailscale HTTPS or `tailscale serve`
there, and never add a tailnet route to T3. The Tailscale wording below describes the general
project and other installations.

## Invariants

- Private LAN/tailnet only. Phone VPN stays off at home, on at coffee; computers'
  Tailscale remains running. Save permanent HTTPS and explicit fixed home Wi-Fi/
  Ethernet routes on the same pairing; learned routes are temporary. Verify routes
  lack "found automatically", then test with phone VPN off. No daily URL edits,
  repeated pairing, always-on phone VPN or unrequested relay. Phone home/laptop away
  with phone VPN off needs a separately agreed path.
- Same T3 release track/protocol everywhere; each host retains its own environment,
  providers and agents. Enable Tailscale HTTPS and Continue threads after restarts.
  Network access only where intended; roaming Mac requires macos/install.sh
  --home-network: router-MAC home recognition, fixed IP at home/DHCP away, LAN port
  closed elsewhere while Tailscale passes. Do not broaden routes or public exposure.
- Linux desktop uses checksum-verified AppImage, not password-prompting .deb;
  macOS uses architecture-matched signed/notarized DMG. Headless Linux uses
  `t3 service install` with restart/lingering and `t3 pair --tailscale`, not the
  desktop installer/watcher. Pair Intel Macs directly; T3 SSH-host setup supports
  Linux/Apple silicon. Preserve configured power policy, not extra wake helpers.
- Existing keepalive starts at login, recovers crashes/orphan backends and republishes
  HTTPS when Tailscale arrives late; normal Quit stays respected. Use durable
  power-recovery for requested repair, not documentation alone or temporary agents.
  Linux offline continuations stay queued without consuming normal failure budget,
  send Codex exactly `continue`, and leave desktop/LAN usable. Apply version-checked
  AppImage repair through linux/install.sh; never patch a signed Mac app.
- Restart/update the T3 hosting this agent last, via its delayed owned job after
  telling the owner. Never kill by name: verify server-runtime.json/SingletonLock
  or macOS lsappinfo identity. Change desktop settings through the app or while quit;
  running T3 overwrites file edits. Preserve user stops, pending IDs and other schedules.
- User-only tokens/logins/pairing use request_secret and mode600 files outside Git;
  never args/chat/logs. Remove temporary pairing secrets/revoke API tokens afterward.
  Mac SSH lacks /usr/local/bin and GUI keychain access: use full paths and diagnose
  the access layer rather than requesting credentials repeatedly.
- Current tool schemas/returned IDs and cursors only. Read recipients before acting;
  reads: limit 1–100, maxCharsPerItem, runLimit 1–50. Queued is not executed. Lost run
  ownership stops calls; reconcile its task, do not switch profiles. Never edit globals.

Verify `tailscale serve status`, cross-device /.well-known/t3/environment version/
orchestrationProtocolVersion, clients in `t3 auth session list`, no unused pairing
links, home/away routes and reboot/offline recovery. Updates are owner-initiated,
password-free; normal Quit stays stopped. T3 Connect plus Device Notifications is
required for phone alerts; Tailscale alone supplies connectivity.

Rerun macos/install.sh after tailscaled rebuilds to restore KeepAlive; wait for
launchctl bootout before bootstrap. Existing power policy remains authoritative.
