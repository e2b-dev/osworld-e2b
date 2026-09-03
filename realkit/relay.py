#!/usr/bin/env python3
"""Secure, lifecycle-aware bridge between OSWorld and an E2B sandbox.

The bridge binds only to localhost. It creates the guest with public traffic
disabled, authenticates every E2B ingress request with the per-sandbox traffic
token, and replaces the sandbox on OSWorld snapshot reverts.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import sys
from dataclasses import dataclass
from typing import Optional

import aiohttp
from aiohttp import web
from e2b import Sandbox

try:
    from .e2b_policy import require_immutable_template_ref
except ImportError:  # Copied into the pinned OSWorld checkout by runner/setup.sh.
    from e2b_policy import require_immutable_template_ref

TEMPLATE = os.environ.get("GUEST_TEMPLATE")
SANDBOX_TIMEOUT_S = int(os.environ.get("SANDBOX_TIMEOUT_S", "3600"))
RELAY_HTTP_TIMEOUT_S = int(os.environ.get("RELAY_HTTP_TIMEOUT_S", "240"))
READY_TIMEOUT_S = int(os.environ.get("GUEST_READY_TIMEOUT_S", "180"))
CONTROL_PORT = int(os.environ.get("E2B_RELAY_CONTROL_PORT", "14999"))
PORT_MAP = {15000: 5000, 19222: 9222, 18080: 8080}
CDP_LOCAL = 19222


@dataclass(frozen=True)
class Guest:
    sandbox: Sandbox
    sandbox_id: str
    traffic_token: str
    hosts: dict[int, str]
    generation: int
    source: str = "template"


class GuestManager:
    def __init__(self) -> None:
        self._guest: Optional[Guest] = None
        self._lock = asyncio.Lock()
        self._replace_lock = asyncio.Lock()
        # OSWorld snapshot name -> E2B snapshot id (memory + filesystem state).
        self._snapshots: dict[str, str] = {}

    async def current(self) -> Guest:
        async with self._lock:
            if self._guest is None:
                raise web.HTTPServiceUnavailable(text="guest is not ready")
            return self._guest

    async def sandbox_id(self) -> str | None:
        async with self._lock:
            return None if self._guest is None else self._guest.sandbox_id

    async def _create(self, generation: int, source: Optional[str] = None) -> Guest:
        template = require_immutable_template_ref(TEMPLATE, "GUEST_TEMPLATE")

        def create_sync() -> Sandbox:
            return Sandbox.create(
                source or template,
                timeout=SANDBOX_TIMEOUT_S,
                network={"allow_public_traffic": False},
                metadata={"workload": "osworld", "generation": str(generation)},
            )

        sandbox = await asyncio.to_thread(create_sync)
        token = getattr(sandbox, "traffic_access_token", None)
        if not token:
            await asyncio.to_thread(sandbox.kill)
            raise RuntimeError("E2B did not return a traffic access token")
        guest = Guest(
            sandbox=sandbox,
            sandbox_id=sandbox.sandbox_id,
            traffic_token=token,
            hosts={port: sandbox.get_host(port) for port in set(PORT_MAP.values())},
            generation=generation,
            source=f"snapshot:{source}" if source else "template",
        )
        try:
            await self._wait_ready(guest)
        except BaseException:
            await asyncio.to_thread(sandbox.kill)
            raise
        return guest

    async def _wait_ready(self, guest: Guest) -> None:
        deadline = asyncio.get_running_loop().time() + READY_TIMEOUT_S
        headers = {"e2b-traffic-access-token": guest.traffic_token}
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while asyncio.get_running_loop().time() < deadline:
                try:
                    url = f"https://{guest.hosts[5000]}/screen_size"
                    async with session.post(url, headers=headers) as response:
                        if response.status == 200:
                            return
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    pass
                await asyncio.sleep(2)
        raise TimeoutError(f"guest {guest.sandbox_id} did not become ready")

    async def replace(self, source: Optional[str] = None) -> Guest:
        async with self._replace_lock:
            async with self._lock:
                generation = 1 if self._guest is None else self._guest.generation + 1
            new_guest = await self._create(generation, source)
            async with self._lock:
                old_guest = self._guest
                self._guest = new_guest
            if old_guest is not None:
                try:
                    await asyncio.to_thread(old_guest.sandbox.kill)
                except Exception as exc:
                    print(
                        f"[relay] warning: could not kill {old_guest.sandbox_id}: {exc}",
                        file=sys.stderr,
                    )
        print(
            f"[relay] guest ready id={new_guest.sandbox_id} generation={generation} template={TEMPLATE}",
            file=sys.stderr,
        )
        return new_guest

    async def save_snapshot(self, name: str) -> str:
        """Capture the current guest's memory + filesystem as an E2B snapshot.

        The sandbox pauses briefly during capture and resumes automatically.
        Snapshots persist independently of the sandbox and can seed any number
        of new sandboxes, so a saved name stays revert-able for the whole run.
        """
        guest = await self.current()
        info = await asyncio.to_thread(guest.sandbox.create_snapshot)
        self._snapshots[name] = info.snapshot_id
        print(
            f"[relay] snapshot saved name={name} id={info.snapshot_id} sandbox={guest.sandbox_id}",
            file=sys.stderr,
        )
        return info.snapshot_id

    async def revert(self, snapshot_name: Optional[str] = None) -> Guest:
        """Replace the guest: from a saved snapshot if the name is known,
        otherwise from the immutable template (OSWorld's default revert names,
        e.g. "init_state", are never explicitly saved and mean base state)."""
        source = self._snapshots.get(snapshot_name) if snapshot_name else None
        return await self.replace(source)

    async def stop(self) -> None:
        async with self._lock:
            guest, self._guest = self._guest, None
        if guest is not None:
            try:
                await asyncio.to_thread(guest.sandbox.kill)
            except Exception as exc:
                print(f"[relay] warning: could not kill {guest.sandbox_id}: {exc}", file=sys.stderr)


manager = GuestManager()
stop_event = asyncio.Event()


def _upstream_headers(request: web.Request, guest: Guest) -> dict[str, str]:
    excluded = {
        "host",
        "connection",
        "content-length",
        "accept-encoding",
        "upgrade",
        "sec-websocket-key",
        "sec-websocket-version",
        "sec-websocket-extensions",
    }
    headers = {key: value for key, value in request.headers.items() if key.lower() not in excluded}
    headers["e2b-traffic-access-token"] = guest.traffic_token
    return headers


def _rewrite_cdp_host(payload: bytes, local_port: int) -> bytes:
    text = payload.decode("utf-8", "replace")
    text = re.sub(r"ws://[^/\"]+/devtools", f"ws://127.0.0.1:{local_port}/devtools", text)
    text = re.sub(r"\"host\":\s*\"[^\"]*\"", f'"host": "127.0.0.1:{local_port}"', text)
    return text.encode()


def make_proxy_handler(local_port: int):
    remote_port = PORT_MAP[local_port]

    async def handler(request: web.Request) -> web.StreamResponse:
        guest = await manager.current()
        target = f"https://{guest.hosts[remote_port]}{request.rel_url}"
        headers = _upstream_headers(request, guest)

        if request.headers.get("Upgrade", "").lower() == "websocket":
            downstream = web.WebSocketResponse(max_msg_size=0)
            await downstream.prepare(request)
            timeout = aiohttp.ClientTimeout(total=None, sock_connect=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                try:
                    upstream = await session.ws_connect(
                        target.replace("https://", "wss://", 1),
                        headers=headers,
                        max_msg_size=0,
                    )
                except Exception as exc:
                    print(f"[relay:{local_port}] websocket connect failed: {exc}", file=sys.stderr)
                    await downstream.close(code=1011, message=b"upstream connect failed")
                    return downstream

                async def upstream_to_downstream() -> None:
                    async for message in upstream:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            await downstream.send_str(message.data)
                        elif message.type == aiohttp.WSMsgType.BINARY:
                            await downstream.send_bytes(message.data)

                async def downstream_to_upstream() -> None:
                    async for message in downstream:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            await upstream.send_str(message.data)
                        elif message.type == aiohttp.WSMsgType.BINARY:
                            await upstream.send_bytes(message.data)

                tasks = [
                    asyncio.create_task(upstream_to_downstream()),
                    asyncio.create_task(downstream_to_upstream()),
                ]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                for task in done:
                    if not task.cancelled() and task.exception() is not None:
                        print(
                            f"[relay:{local_port}] websocket error: {task.exception()}",
                            file=sys.stderr,
                        )
                await upstream.close()
                await downstream.close()
                return downstream

        body = await request.read()
        timeout = aiohttp.ClientTimeout(total=RELAY_HTTP_TIMEOUT_S)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(
                    request.method,
                    target,
                    headers=headers,
                    data=body or None,
                    allow_redirects=False,
                ) as response:
                    payload = await response.read()
                    if local_port == CDP_LOCAL and "json" in response.headers.get(
                        "Content-Type", ""
                    ):
                        payload = _rewrite_cdp_host(payload, local_port)
                    excluded = {
                        "content-length",
                        "transfer-encoding",
                        "content-encoding",
                        "connection",
                        "e2b-traffic-access-token",
                    }
                    out_headers = {
                        key: value
                        for key, value in response.headers.items()
                        if key.lower() not in excluded
                    }
                    return web.Response(status=response.status, body=payload, headers=out_headers)
        except asyncio.TimeoutError:
            raise web.HTTPGatewayTimeout(
                text=f"upstream exceeded {RELAY_HTTP_TIMEOUT_S}s relay timeout"
            )
        except aiohttp.ClientError as exc:
            raise web.HTTPBadGateway(text=f"upstream request failed: {exc}")

    return handler


def _public_state(guest: Guest) -> dict[str, object]:
    return {
        "ready": True,
        "sandbox_id": guest.sandbox_id,
        "generation": guest.generation,
        "template": TEMPLATE,
        "source": guest.source,
        "sandbox_timeout_seconds": SANDBOX_TIMEOUT_S,
        "restricted_ingress": True,
    }


async def health(_: web.Request) -> web.Response:
    return web.json_response(_public_state(await manager.current()))


async def reset(request: web.Request) -> web.Response:
    snapshot_name = None
    if request.can_read_body:
        try:
            snapshot_name = (await request.json()).get("snapshot")
        except Exception:
            raise web.HTTPBadRequest(text='reset body must be JSON like {"snapshot": "name"}')
    return web.json_response(_public_state(await manager.revert(snapshot_name)))


async def save(request: web.Request) -> web.Response:
    try:
        name = (await request.json()).get("name")
    except Exception:
        name = None
    if not name:
        raise web.HTTPBadRequest(text='save body must be JSON like {"name": "snapshot-name"}')
    snapshot_id = await manager.save_snapshot(name)
    state = _public_state(await manager.current())
    return web.json_response({"saved": name, "snapshot_id": snapshot_id, **state})


async def stop(_: web.Request) -> web.Response:
    stop_event.set()
    return web.json_response({"stopping": True, "sandbox_id": await manager.sandbox_id()})


async def main() -> None:
    await manager.replace()
    runners: list[web.AppRunner] = []
    try:
        for local_port in PORT_MAP:
            app = web.Application(client_max_size=1024**3)
            app.router.add_route("*", "/{tail:.*}", make_proxy_handler(local_port))
            runner = web.AppRunner(app)
            await runner.setup()
            await web.TCPSite(runner, "127.0.0.1", local_port).start()
            runners.append(runner)

        control = web.Application()
        control.router.add_get("/health", health)
        control.router.add_get("/state", health)
        control.router.add_post("/reset", reset)
        control.router.add_post("/save", save)
        control.router.add_post("/stop", stop)
        control_runner = web.AppRunner(control)
        await control_runner.setup()
        await web.TCPSite(control_runner, "127.0.0.1", CONTROL_PORT).start()
        runners.append(control_runner)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass
        print(
            json.dumps({"event": "RELAY_READY", **_public_state(await manager.current())}),
            file=sys.stderr,
        )
        await stop_event.wait()
    finally:
        await manager.stop()
        for runner in reversed(runners):
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
