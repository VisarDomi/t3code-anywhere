# Connections that survive changing networks

Use a permanent Tailscale HTTPS route for each computer and keep Tailscale connected
on every device. A fixed home LAN address and a permanent tailnet address serve
different purposes: the home address works only on that home network; the tailnet
name continues to reach the computer after it moves.

## One-time phone setup

1. Pair each computer using `https://<name>.<tailnet>.ts.net/`, as in the runbook.
   In T3's environment details, verify that HTTPS route is saved without the label
   "found automatically". Keep an existing valid pairing; do not delete it just
   because a LAN route times out.
2. In the Tailscale iOS app, open profile/settings → **VPN On Demand**, enable it,
   and set **Wi-Fi: Always** and **Cellular: Always**. Do not exclude home Wi-Fi.
   Connect Tailscale. These are the [documented connection rules](https://tailscale.com/docs/features/client/ios-vpn-on-demand).
3. Leave Tailscale connected on both computers, with T3's **Tailscale HTTPS** on.
   No exit node is required. Complete a coffee shop's Wi-Fi sign-in when needed.

The phone needs Tailscale when either endpoint is away. A rule that turns it off
whenever the phone is home cannot reach a laptop at a coffee shop. There is no
phone URL change when moving between these cases:

| Desktop | Laptop | Phone | Connection available |
| --- | --- | --- | --- |
| Home | Home | Home | Tailscale; current LAN shortcuts may also work |
| Home | Away | Home | Tailscale to both computers |
| Home | Home | Away | Tailscale to both computers |
| Home | Away | Away | Tailscale to both computers, even on different networks |

Each device needs working internet, the same tailnet, a valid pairing and compatible
T3 versions; host computers must be awake with T3 running. These are setup
requirements, not a claim that every physical network transition was tested.

## Why an unfamiliar LAN address can appear

T3's server reports private IPv4 addresses from its current network interfaces.
With Network access on, clients learn these as routes marked **found automatically**.
They can include a laptop's DHCP address on another Wi-Fi network. That does not
change its configured static home address, nor does it make the foreign address
reachable from home.

Learned routes are a snapshot, not a permanent address book. When the server reports
a different set, T3 drops learned routes missing from that set. After a laptop
travels, the phone can therefore retain a foreign LAN address and no home LAN
address until its next successful connection. If Tailscale is disconnected, none
of the remaining routes may work, so the phone cannot learn the home address again.

This behavior is explicit in T3 version `0.0.46-nightly.20261013.3053`:
[server address discovery](https://github.com/pingdotgg/t3code/blob/6524a8d43795dc543f7cfb572388cdea3662ad48/apps/server/src/environment/DirectEndpoints.ts),
[route merging](https://github.com/pingdotgg/t3code/blob/6524a8d43795dc543f7cfb572388cdea3662ad48/packages/client-runtime/src/connection/routes.ts), and
[tests for replacing learned addresses and retaining saved routes](https://github.com/pingdotgg/t3code/blob/6524a8d43795dc543f7cfb572388cdea3662ad48/packages/client-runtime/src/connection/routes.test.ts).
Recheck these behaviors after relevant T3 updates.

## Recovering a phone with a stale LAN route

If the permanent Tailscale HTTPS route is already saved, connect Tailscale and let
T3 retry (or tap its reconnect button). The successful connection lets T3 learn the
computer's current LAN routes. **Do not replace the environment URL with today's
LAN address as the roaming fix.** That fixes only the current network.

If the HTTPS route is absent or itself marked "found automatically", add a saved
route using a new pairing link whose base URL is the permanent HTTPS name. Keep
the existing environment; T3's **Routes → Add route** pairs another route to it.
Do not remove the working saved route or its credential.

## Optional local access with Tailscale deliberately off

This is optional and only covers devices on the same home LAN. If the owner needs
it to survive a laptop's travel, explicitly add saved routes for each fixed home
interface address using **Add route** and pairing links for those addresses.
Verify they are not marked "found automatically". User-saved routes survive changes
in the server's reported addresses; merely learning or reordering a route does not
make it permanent. Preserve the Tailscale HTTPS route as well.

Keep a laptop's static Wi-Fi address restricted to its home network and DHCP
elsewhere, using the home-network helper. Do not apply the home address at a coffee
shop, alias a stale foreign address onto the home interface, or open the laptop's
T3 port to foreign Wi-Fi to repair a client route.

## Verify before calling the setup complete

- From the other computer, fetch each host's
  `https://<name>.<tailnet>.ts.net/.well-known/t3/environment` and check its identity
  and protocol version. Confirm Serve still targets the active backend port.
- On the phone, confirm each environment connects with Tailscale on and its
  permanent HTTPS route retained. Then check phone cellular, laptop away, and the
  return home when those physical transitions are available. Do not claim these
  phone tests passed based only on computer-to-computer requests.
- If local access without Tailscale was requested, verify the explicitly saved
  home routes, including with the cable disconnected, rather than relying on the
  current learned route list.
