#!/usr/bin/env bash
# PATH shim installed at /usr/local/bin/socat (shadows /usr/bin/socat).
#
# OSWorld chrome task configs expose CDP with:
#   ["google-chrome", "--remote-debugging-port=1337"]
#   ["socat", "tcp-listen:9222,fork", "tcp:localhost:1337"]
# A plain TCP forward is not enough through E2B's ingress: the proxy rewrites
# the HTTP Host header to the routing subdomain (9222-{id}.e2b.app) and
# Chrome's DevTools endpoint rejects any non-localhost Host ("Invalid host").
# For exactly that :9222 forward, substitute the host-normalizing CDP proxy
# (rewrites Host -> 127.0.0.1:1337, proxies HTTP + the CDP WebSocket). All 78
# task configs in the pinned checkout that launch Chrome use 1337, which
# cdp_hostfix.py hardcodes as its target. Any other socat use passes through.
if [[ "$*" == *"tcp-listen:9222"* ]]; then
    # A GUI relaunch can leave the already-baked proxy listening on 9222.
    /usr/bin/ss -ltn 2>/dev/null | /usr/bin/grep -q ':9222 ' && exit 0
    exec /usr/bin/python3 /opt/osworld-server/cdp_hostfix.py
fi
exec /usr/bin/socat "$@"
