# Home LAN and coffee-shop Tailscale

The daily routine is one phone toggle: **Tailscale off at home, on at coffee**.
Save both home LAN routes and a Tailscale HTTPS route for each computer. The
computers keep their Tailscale services running for remote access; home traffic
uses LAN routes and the phone does not need its VPN at home.

## Supported cases

| Desktop | Laptop | Phone | Phone VPN | Connections |
| --- | --- | --- | --- | --- |
| Home | Home | Home | Off | Phone to both computers over LAN; computers use LAN |
| Home | Home | Coffee | On | Phone to both over Tailscale; computers can use LAN |
| Home | Coffee | Coffee | On | Phone to both and laptop to desktop over Tailscale |

The phone and laptop can be on different outside networks in the last case.
**Phone home / laptop away with the phone VPN off is outside this profile.** If
needed, agree on another connection path before setup. Do not silently add a relay
or change the owner's phone VPN policy.

Hosts must be awake with T3 running. Outside networks need working internet,
including any Wi-Fi sign-in. Keep every device on compatible T3 versions and the
same tailnet, with valid pairings. Network and host failures can still interrupt
connections; this policy removes recurring route edits and pairing from travel.

## One-time saved routes

For every client that must work locally without its VPN, including the phone:

1. Keep its existing saved `https://<name>.<tailnet>.ts.net/` route. If setting up
   from scratch, pair through that name with Tailscale on first.
2. At home, create a new pairing link on each host for each fixed LAN address:

   ```sh
   umask 077
   ~/.t3/bin/t3 auth pairing create --base-url http://<fixed-home-ip>:<t3-port> \
     --label phone-home --ttl 7d --json </dev/null > /path/to/private-pairing.json
   ```

   Treat the resulting link/code as a secret. Keep it out of repositories and
   command-line arguments; show the owner its QR code for pairing. Generate a
   separate single-use link per route and client.
3. On the phone, open the existing environment → **Routes → Add route** and scan
   its home-route QR code. This adds a route to the same machine, preserving the
   environment, threads and existing HTTPS route. Include each fixed home Wi-Fi
   and Ethernet address that must work independently, plus the desktop's fixed
   address. The interface being added must be connected and reachable during
   pairing; a QR code cannot pair an unplugged Ethernet interface.
4. Verify that the added LAN routes are **not** labelled "found automatically".
   Keep the LAN routes ahead of the HTTPS route; Wi-Fi first is suitable when the
   cable is optional. Adding a route normally inserts it ahead of Tailscale.
5. Turn the phone's Tailscale **off**. Confirm both computers connect, including
   with the laptop cable disconnected. Turn it **on** when leaving for coffee.
   Returning home requires only turning it off again, not editing a URL.

Do not replace an environment's displayed URL as the default repair. In the T3
version inspected, that edits the first direct route and requires that route's
own saved credential; a learned route can borrow another route's credential.
**Add route** creates a saved route with its own credential and retains the
existing Tailscale route. Do not delete the environment or its working HTTPS
route. Delete consumed QR/link files after verifying successful pairing; revoke
unused pairing codes when abandoning setup.

Before pairing home routes, give each required home interface a stable address
using a router DHCP reservation or an appropriate OS configuration. Choose unused
addresses for the owner's network; do not copy another person's addresses.
A laptop keeps its home
Wi-Fi address only at home and uses DHCP elsewhere. On Mac laptops, Network access
must be combined with the home-network firewall helper, which blocks the T3 port
on foreign LANs while allowing Tailscale. Do not apply a home IP at a coffee shop
or open T3 to foreign Wi-Fi to repair a stale client route.

## Why automatic discovery is insufficient

T3 reports its current private interface addresses, and clients add them as routes
marked **found automatically**. A foreign DHCP address can therefore appear on a
phone without changing the laptop's configured static home address. These learned
routes are replaced when the server reports a new set. An old home address can
vanish, and the phone cannot relearn it while none of its remaining routes work.

Explicitly saved routes survive changes in the server's reports. Merely learning
or reordering a route does not make it permanent. Saving all required fixed home
routes alongside HTTPS prevents this dependency on the last visited network.

Source references for T3 `0.0.46-nightly.20261013.3053`:
[interface discovery](https://github.com/pingdotgg/t3code/blob/6524a8d43795dc543f7cfb572388cdea3662ad48/apps/server/src/environment/DirectEndpoints.ts),
[route retention](https://github.com/pingdotgg/t3code/blob/6524a8d43795dc543f7cfb572388cdea3662ad48/packages/client-runtime/src/connection/routes.ts),
[route tests](https://github.com/pingdotgg/t3code/blob/6524a8d43795dc543f7cfb572388cdea3662ad48/packages/client-runtime/src/connection/routes.test.ts), and
[pairing and URL editing](https://github.com/pingdotgg/t3code/blob/6524a8d43795dc543f7cfb572388cdea3662ad48/packages/client-runtime/src/connection/onboarding.ts).
Recheck these behaviors after relevant T3 updates.

## Verify and hand over

- Check home LAN and Tailscale HTTPS discovery endpoints from the other computer,
  verifying the environment identity and protocol version. Confirm Serve targets
  the active backend port. Confirm saved LAN routes on the computer clients too;
  do not confuse LAN traffic inside Tailscale with a direct LAN route.
- Have the owner confirm the phone works with its VPN off, both saved home routes
  survive travel, and the phone reconnects with its VPN on away from home.
- Test the home-network firewall's away state without publishing to foreign LANs,
  and check login startup, crash recovery and offline-boot Serve repair as needed.
- Report physical transitions or phone tests still pending. Computer-only HTTP
  checks do not prove that a phone has saved its routes. Leave the owner's phone
  under their control; no phone automation unless they explicitly authorize it.
