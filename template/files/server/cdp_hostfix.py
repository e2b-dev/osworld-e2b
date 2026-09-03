#!/usr/bin/env python3
"""Guest-side CDP host-normalizing proxy (replaces socat for :9222).

E2B's public ingress rewrites the HTTP Host header to the routing subdomain
`9222-{id}.e2b.app` before it reaches the guest. Chrome's DevTools endpoint
rejects that Host ("Invalid host", 400). This proxy sits on :9222 inside the
guest, rewrites Host -> 127.0.0.1:1337 so Chrome accepts the request, and
proxies both HTTP and the CDP WebSocket to Chrome on :1337. Run Chrome with
--remote-allow-origins=* so the WS upgrade's Origin check also passes.
"""

import asyncio
import sys

import aiohttp
from aiohttp import web

TARGET = "http://127.0.0.1:1337"
LISTEN = 9222


async def handler(request: web.Request):
    target = TARGET + str(request.rel_url)
    if request.headers.get("Upgrade", "").lower() == "websocket":
        ws_server = web.WebSocketResponse(max_msg_size=0)
        await ws_server.prepare(request)
        session = aiohttp.ClientSession()
        try:
            up = await asyncio.wait_for(
                session.ws_connect(
                    target.replace("http://", "ws://", 1),
                    max_msg_size=0,
                    headers={"Host": "127.0.0.1:1337"},
                ),
                timeout=15,
            )
        except Exception as e:
            print(f"[cdp_hostfix] upstream connect err: {e}", file=sys.stderr)
            await session.close()
            await ws_server.close()
            return ws_server
        try:

            async def a():
                async for m in up:
                    if m.type == aiohttp.WSMsgType.TEXT:
                        await ws_server.send_str(m.data)
                    elif m.type == aiohttp.WSMsgType.BINARY:
                        await ws_server.send_bytes(m.data)
                    elif m.type in (
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.CLOSING,
                    ):
                        break

            async def b():
                async for m in ws_server:
                    if m.type == aiohttp.WSMsgType.TEXT:
                        await up.send_str(m.data)
                    elif m.type == aiohttp.WSMsgType.BINARY:
                        await up.send_bytes(m.data)
                    elif m.type in (
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.CLOSING,
                    ):
                        break

            # FIRST_COMPLETED + cancel, not gather: one side closing silently
            # must not leave the other await leaking the chrome connection.
            done, pending = await asyncio.wait(
                [asyncio.create_task(a()), asyncio.create_task(b())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
        except Exception as e:
            print(f"[cdp_hostfix] ws err: {e}", file=sys.stderr)
        finally:
            await up.close()
            await session.close()
            await ws_server.close()
        return ws_server

    body = await request.read()
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in ("host", "connection", "content-length", "accept-encoding")
    }
    headers["Host"] = "127.0.0.1:1337"
    async with aiohttp.ClientSession() as s:
        async with s.request(
            request.method, target, headers=headers, data=body or None, allow_redirects=False
        ) as r:
            raw = await r.read()
            out = {
                k: v
                for k, v in r.headers.items()
                if k.lower()
                not in ("content-length", "transfer-encoding", "content-encoding", "connection")
            }
            return web.Response(status=r.status, body=raw, headers=out)


async def main():
    app = web.Application(client_max_size=1024**3)
    app.router.add_route("*", "/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", LISTEN).start()
    print("CDP_HOSTFIX_READY", file=sys.stderr)
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
