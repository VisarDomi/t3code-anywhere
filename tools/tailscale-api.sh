#!/bin/sh
# Tailnet admin steps through the Tailscale API, so nobody clicks through the console.
# The owner creates an API access token (admin console → Settings → Keys → Generate
# access token; 1 day is enough) and it is saved, mode 600, in TS_API_TOKEN_FILE
# (default ~/.config/t3code-anywhere/tailscale-api-token). Never on a command line.
#
#   tools/tailscale-api.sh check              MagicDNS and HTTPS certificates on?
#   tools/tailscale-api.sh https-on           turn on HTTPS certificates (needed by T3)
#   tools/tailscale-api.sh auth-key FILE      1-day reusable, pre-approved device key → FILE
#   tools/tailscale-api.sh no-expiry HOST     never expire this device's key
#   tools/tailscale-api.sh revoke-token       revoke the API token and delete its file
set -eu
case ${1:-} in check | https-on | auth-key | no-expiry | revoke-token) ;; *) sed -n '2,13p' "$0"; exit 2 ;; esac
token_file=${TS_API_TOKEN_FILE:-$HOME/.config/t3code-anywhere/tailscale-api-token}
[ -r "$token_file" ] || { echo "no API token in $token_file" >&2; exit 1; }

api() {   # METHOD PATH [JSON]; the token goes in through a curl config on stdin
    printf 'header = "Authorization: Bearer %s"\n' "$(cat "$token_file")" |
        curl -sS -K - -X "$1" ${3:+-H 'Content-Type: application/json' --data "$3"} \
            "${TS_API_URL:-https://api.tailscale.com/api/v2}$2"
}
json() {  # PYTHON-CODE [ARGS...]: run with the response as `d`, ARGS as sys.argv[1:]
    code=$1
    shift
    python3 -I -c "import json, sys; d = json.load(sys.stdin); $code" "$@"
}

case ${1:-} in
check)
    api GET /tailnet/-/settings | json 'print("HTTPS certificates:", "on" if d.get("httpsEnabled") else "OFF (run https-on)") if "httpsEnabled" in d else sys.exit(str(d))'
    api GET /tailnet/-/dns/preferences | json 'print("MagicDNS:", "on" if d.get("magicDNS") else "OFF (turn it on in the admin console, DNS page)")' ;;
https-on)
    api PATCH /tailnet/-/settings '{"httpsEnabled":true}' >/dev/null
    "$0" check ;;
auth-key)
    out=${2:?file to write the key to}
    # Descriptions accept letters, digits, spaces and hyphens only.
    umask 077
    api POST /tailnet/-/keys '{"description":"t3code-anywhere setup","expirySeconds":86400,"capabilities":{"devices":{"create":{"reusable":true,"ephemeral":false,"preauthorized":true}}}}' |
        json 'open(sys.argv[1], "w").write(d["key"]) if "key" in d else sys.exit(str(d))' "$out"
    echo "device key written to $out (valid 1 day; use: tailscale up --auth-key=file:$out)" ;;
no-expiry)
    host=${2:?device hostname}
    id=$(api GET /tailnet/-/devices | json '
host = sys.argv[1].lower()
ids = [x["id"] for x in d["devices"] if x["hostname"].lower() == host or x["name"].split(".")[0] == host]
print(ids[0]) if ids else sys.exit("no device " + host)' "$host")
    api POST "/device/$id/key" '{"keyExpiryDisabled":true}' >/dev/null
    api GET "/device/$id" | json 'print(d["name"], "key expiry disabled" if d.get("keyExpiryDisabled") else "key expiry STILL ON")' ;;
revoke-token)
    # tskey-api-<id>-<secret>
    id=$(sed -n 's/^tskey-api-\([^-]*\)-.*/\1/p' "$token_file")
    api DELETE "/tailnet/-/keys/$id" >/dev/null
    rm -f "$token_file"
    echo "API token $id revoked" ;;
esac
