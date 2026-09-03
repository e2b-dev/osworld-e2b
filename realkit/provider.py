"""E2B provider for OSWorld.

The localhost relay owns E2B credentials and sandbox objects. OSWorld's
snapshot-revert hook asks it to replace the guest with a fresh sandbox.
"""

from __future__ import annotations

import json
import logging
import os
from urllib.request import Request, urlopen

from desktop_env.providers.base import Provider

logger = logging.getLogger("desktopenv.providers.e2b")
CONTROL_URL = os.environ.get("E2B_RELAY_CONTROL_URL", "http://127.0.0.1:14999")


def _control(path: str, method: str = "GET", timeout: int = 300, payload: dict = None):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"} if data else {}
    request = Request(f"{CONTROL_URL}{path}", method=method, data=data, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


class E2BProvider(Provider):
    def __init__(self, region: str = None):
        self.region = region

    def start_emulator(self, path_to_vm: str, headless: bool, os_type: str = None, *args, **kwargs):
        state = _control("/health")
        logger.info("E2B guest ready: %s", state["sandbox_id"])

    def get_ip_address(self, path_to_vm: str) -> str:
        # host:server_port:chromium_port:vnc_port:vlc_port. This integration is
        # headless, so 0 is intentionally returned for the unavailable VNC port.
        return "127.0.0.1:15000:19222:0:18080"

    def save_state(self, path_to_vm: str, snapshot_name: str):
        # E2B snapshots capture the exact running state (memory + filesystem)
        # and can seed any number of new sandboxes, matching QEMU's named
        # mid-run snapshots. The sandbox pauses briefly and resumes.
        state = _control("/save", method="POST", payload={"name": snapshot_name})
        logger.info("E2B snapshot saved: %s -> %s", snapshot_name, state["snapshot_id"])

    def revert_to_snapshot(self, path_to_vm: str, snapshot_name: str) -> str:
        # A name saved via save_state reverts to that exact running state; any
        # other name (e.g. OSWorld's default "init_state") means the template
        # base state via a fresh sandbox.
        state = _control("/reset", method="POST", payload={"snapshot": snapshot_name})
        logger.info(
            "E2B guest replaced: %s (generation %s, source %s)",
            state["sandbox_id"],
            state["generation"],
            state.get("source", "template"),
        )
        return path_to_vm

    def stop_emulator(self, path_to_vm: str, *args, **kwargs):
        try:
            _control("/stop", method="POST", timeout=30)
        except Exception as exc:
            logger.warning("Could not stop E2B relay cleanly: %s", exc)
