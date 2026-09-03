from __future__ import annotations

import unittest
from threading import Event
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import make_mocked_request

from realkit import relay


class FakeSandbox:
    created = []

    def __init__(self, sandbox_id):
        self.sandbox_id = sandbox_id
        self.traffic_access_token = f"token-{sandbox_id}"
        self.killed = False

    @classmethod
    def create(cls, template, **kwargs):
        sandbox = cls(f"sandbox-{len(cls.created) + 1}")
        sandbox.create_template = template
        sandbox.create_kwargs = kwargs
        cls.created.append(sandbox)
        return sandbox

    def get_host(self, port):
        return f"{port}-{self.sandbox_id}.example.test"

    def kill(self):
        self.killed = True

    def create_snapshot(self):
        class SnapshotInfo:
            snapshot_id = f"snap-of-{self.sandbox_id}"

        return SnapshotInfo()


class FlakyKillSandbox(FakeSandbox):
    def __init__(self, sandbox_id):
        super().__init__(sandbox_id)
        self.kill_attempts = 0

    def kill(self):
        self.kill_attempts += 1
        if self.kill_attempts < 3:
            raise RuntimeError("transient cleanup failure")
        self.killed = True


class RelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        FakeSandbox.created.clear()
        self.manager = relay.GuestManager()
        self.template_patch = patch.object(
            relay,
            "TEMPLATE",
            "osworld-gnome:62e8be41-4106-4850-96ea-afc822735b89",
        )
        self.template_patch.start()
        self.addCleanup(self.template_patch.stop)

    async def test_replace_uses_restricted_ingress_and_kills_previous_guest(self):
        with (
            patch.object(relay, "Sandbox", FakeSandbox),
            patch.object(self.manager, "_wait_ready", AsyncMock()),
        ):
            first = await self.manager.replace()
            second = await self.manager.replace()

        self.assertEqual(first.generation, 1)
        self.assertEqual(second.generation, 2)
        self.assertNotEqual(first.sandbox_id, second.sandbox_id)
        self.assertTrue(FakeSandbox.created[0].killed)
        self.assertFalse(FakeSandbox.created[1].killed)
        self.assertEqual(
            FakeSandbox.created[1].create_kwargs["network"],
            {"allow_public_traffic": False},
        )

    async def test_ingress_token_is_added_but_not_exposed_by_state(self):
        guest = relay.Guest(
            sandbox=FakeSandbox("sandbox-1"),
            sandbox_id="sandbox-1",
            traffic_token="top-secret",
            hosts={5000: "host"},
            generation=1,
        )
        request = make_mocked_request(
            "POST",
            "/execute",
            headers={"Host": "localhost", "Connection": "keep-alive", "X-Test": "yes"},
        )
        headers = relay._upstream_headers(request, guest)
        self.assertEqual(headers["e2b-traffic-access-token"], "top-secret")
        self.assertNotIn("Host", headers)
        self.assertEqual(headers["X-Test"], "yes")
        self.assertNotIn("traffic_token", relay._public_state(guest))

    async def test_saved_snapshot_reverts_to_running_state_source(self):
        with (
            patch.object(relay, "Sandbox", FakeSandbox),
            patch.object(self.manager, "_wait_ready", AsyncMock()),
        ):
            first = await self.manager.replace()
            snapshot_id = await self.manager.save_snapshot("mid_task")
            reverted = await self.manager.revert("mid_task")

        self.assertEqual(snapshot_id, f"snap-of-{first.sandbox_id}")
        self.assertEqual(FakeSandbox.created[1].create_template, snapshot_id)
        self.assertEqual(reverted.source, f"snapshot:{snapshot_id}")
        self.assertEqual(
            FakeSandbox.created[1].create_kwargs["network"],
            {"allow_public_traffic": False},
        )

    async def test_unknown_snapshot_name_falls_back_to_template(self):
        with (
            patch.object(relay, "Sandbox", FakeSandbox),
            patch.object(self.manager, "_wait_ready", AsyncMock()),
        ):
            await self.manager.replace()
            reverted = await self.manager.revert("init_state")

        self.assertEqual(FakeSandbox.created[1].create_template, relay.TEMPLATE)
        self.assertEqual(reverted.source, "template")

    async def test_failed_replacement_kills_candidate_and_preserves_current_guest(self):
        with (
            patch.object(relay, "Sandbox", FakeSandbox),
            patch.object(self.manager, "_wait_ready", AsyncMock()),
        ):
            first = await self.manager.replace()

        with (
            patch.object(relay, "Sandbox", FakeSandbox),
            patch.object(
                self.manager,
                "_wait_ready",
                AsyncMock(side_effect=TimeoutError("not ready")),
            ),
            self.assertRaisesRegex(TimeoutError, "not ready"),
        ):
            await self.manager.replace()

        self.assertIs((await self.manager.current()), first)
        self.assertFalse(FakeSandbox.created[0].killed)
        self.assertTrue(FakeSandbox.created[1].killed)

    async def test_stop_kills_active_guest_once_and_is_idempotent(self):
        with (
            patch.object(relay, "Sandbox", FakeSandbox),
            patch.object(self.manager, "_wait_ready", AsyncMock()),
        ):
            guest = await self.manager.replace()

        await self.manager.stop()
        await self.manager.stop()

        self.assertTrue(guest.sandbox.killed)
        with self.assertRaises(relay.web.HTTPServiceUnavailable):
            await self.manager.current()

    async def test_stop_racing_inflight_create_reaps_candidate(self):
        create_started = Event()
        allow_create = Event()

        class BlockingSandbox(FakeSandbox):
            @classmethod
            def create(cls, template, **kwargs):
                create_started.set()
                if not allow_create.wait(timeout=5):
                    raise TimeoutError("test did not release sandbox creation")
                return super().create(template, **kwargs)

        with (
            patch.object(relay, "Sandbox", BlockingSandbox),
            patch.object(self.manager, "_wait_ready", AsyncMock()),
        ):
            replacement = relay.asyncio.create_task(self.manager.replace())
            await relay.asyncio.to_thread(create_started.wait, 5)
            stopping = relay.asyncio.create_task(self.manager.stop())
            await relay.asyncio.sleep(0)
            allow_create.set()
            await stopping
            with self.assertRaisesRegex(RuntimeError, "stopped"):
                await replacement

        self.assertEqual(len(FakeSandbox.created), 1)
        self.assertTrue(FakeSandbox.created[0].killed)
        with self.assertRaises(relay.web.HTTPServiceUnavailable):
            await self.manager.current()

    async def test_replacement_retries_transient_old_guest_cleanup(self):
        with (
            patch.object(relay, "Sandbox", FlakyKillSandbox),
            patch.object(self.manager, "_wait_ready", AsyncMock()),
        ):
            first = await self.manager.replace()
            await self.manager.replace()

        self.assertTrue(first.sandbox.killed)
        self.assertEqual(first.sandbox.kill_attempts, 3)

    async def test_stop_retries_old_guest_cleanup_that_remained_pending(self):
        class RecoverableKillSandbox(FakeSandbox):
            def __init__(self, sandbox_id):
                super().__init__(sandbox_id)
                self.allow_kill = sandbox_id != "sandbox-1"

            def kill(self):
                if not self.allow_kill:
                    raise RuntimeError("persistent cleanup failure")
                self.killed = True

        with (
            patch.object(relay, "Sandbox", RecoverableKillSandbox),
            patch.object(self.manager, "_wait_ready", AsyncMock()),
        ):
            first = await self.manager.replace()
            second = await self.manager.replace()
            self.assertFalse(first.sandbox.killed)
            first.sandbox.allow_kill = True
            await self.manager.stop()

        self.assertTrue(first.sandbox.killed)
        self.assertTrue(second.sandbox.killed)

    async def test_cdp_discovery_is_rewritten_to_local_relay(self):
        payload = b'{"webSocketDebuggerUrl":"ws://upstream/devtools/browser/1","host":"upstream"}'
        rewritten = relay._rewrite_cdp_host(payload, 19222).decode()
        self.assertIn("ws://127.0.0.1:19222/devtools/browser/1", rewritten)
        self.assertIn('"host": "127.0.0.1:19222"', rewritten)


if __name__ == "__main__":
    unittest.main()
