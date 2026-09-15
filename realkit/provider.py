"""E2B provider for OSWorld with one private relay per environment."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from desktop_env.providers.base import Provider

try:
    from .e2b_policy import require_immutable_template_ref
    from .ports import PortBundle, reserve_port_bundle
except ImportError:  # Copied into the pinned OSWorld checkout by runner/setup.sh.
    from e2b_policy import require_immutable_template_ref
    from ports import PortBundle, reserve_port_bundle

logger = logging.getLogger("desktopenv.providers.e2b")
RELAY_ENV_KEYS = {
    "ALL_PROXY",
    "CURL_CA_BUNDLE",
    "DYLD_LIBRARY_PATH",
    "GUEST_READY_TIMEOUT_S",
    "HOME",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "LD_LIBRARY_PATH",
    "NO_PROXY",
    "PATH",
    "PYTHONPATH",
    "RELAY_HTTP_TIMEOUT_S",
    "REQUESTS_CA_BUNDLE",
    "SANDBOX_TIMEOUT_S",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "SYSTEMROOT",
    "TMPDIR",
    "VIRTUAL_ENV",
}


def _relay_environment() -> dict[str, str]:
    return {
        name: value
        for name, value in os.environ.items()
        if name in RELAY_ENV_KEYS or name.startswith("E2B_")
    }


class E2BProvider(Provider):
    def __init__(self, region: str = None):
        self.region = region
        self.ports: PortBundle = reserve_port_bundle()
        self.control_url = f"http://127.0.0.1:{self.ports.control}"
        self._relay: subprocess.Popen | None = None
        self._relay_streams: list[object] = []

    def _control(
        self,
        path: str,
        method: str = "GET",
        timeout: int = 300,
        payload: dict | None = None,
    ) -> dict:
        data = None if payload is None else json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"} if data else {}
        request = Request(f"{self.control_url}{path}", method=method, data=data, headers=headers)
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)

    def _relay_path(self) -> Path:
        configured = os.environ.get("E2B_RELAY_PATH")
        if configured:
            return Path(configured).resolve()
        return Path(__file__).resolve().parents[3] / "e2b_relay.py"

    def _attempt_dir(self) -> Path:
        configured = os.environ.get("E2B_ATTEMPT_DIR")
        if configured:
            path = Path(configured)
            path.mkdir(parents=True, exist_ok=True)
            return path
        return Path(tempfile.mkdtemp(prefix="osworld-e2b-relay-"))

    def start_emulator(
        self,
        path_to_vm: str,
        headless: bool,
        os_type: str = None,
        *args,
        **kwargs,
    ):
        require_immutable_template_ref(path_to_vm, "path_to_vm")
        if self._relay is not None and self._relay.poll() is None:
            state = self._control("/health")
            logger.info("E2B guest ready: %s", state["sandbox_id"])
            return

        attempt_dir = self._attempt_dir()
        stdout = (attempt_dir / "relay.stdout.log").open("ab")
        stderr = (attempt_dir / "relay.stderr.log").open("ab")
        self._relay_streams = [stdout, stderr]
        environment = {
            **_relay_environment(),
            "GUEST_TEMPLATE": path_to_vm,
            "E2B_RELAY_CONTROL_PORT": str(self.ports.control),
            "E2B_RELAY_SERVER_PORT": str(self.ports.server),
            "E2B_RELAY_CHROMIUM_PORT": str(self.ports.chromium),
            "E2B_RELAY_VLC_PORT": str(self.ports.vlc),
            "E2B_RELAY_EVENT_LOG": str(attempt_dir / "relay-events.jsonl"),
        }
        try:
            self._relay = subprocess.Popen(
                [sys.executable, str(self._relay_path())],
                env=environment,
                stdout=stdout,
                stderr=stderr,
            )
            ready_timeout = int(os.environ.get("GUEST_READY_TIMEOUT_S", "180")) + 30
            deadline = time.monotonic() + ready_timeout
            last_error: Exception | None = None
            while time.monotonic() < deadline:
                if self._relay.poll() is not None:
                    raise RuntimeError(f"E2B relay exited with code {self._relay.returncode}")
                try:
                    state = self._control("/health", timeout=5)
                    logger.info("E2B guest ready: %s", state["sandbox_id"])
                    return
                except (OSError, URLError) as error:
                    last_error = error
                    time.sleep(0.2)
            raise TimeoutError(f"E2B relay did not become ready: {last_error}")
        except BaseException:
            self._stop_relay_process()
            raise

    def get_ip_address(self, path_to_vm: str) -> str:
        return f"127.0.0.1:{self.ports.server}:{self.ports.chromium}:0:{self.ports.vlc}"

    def save_state(self, path_to_vm: str, snapshot_name: str):
        state = self._control("/save", method="POST", payload={"name": snapshot_name})
        logger.info("E2B snapshot saved: %s -> %s", snapshot_name, state["snapshot_id"])

    def revert_to_snapshot(self, path_to_vm: str, snapshot_name: str) -> str:
        state = self._control("/reset", method="POST", payload={"snapshot": snapshot_name})
        logger.info(
            "E2B guest replaced: %s (generation %s, source %s)",
            state["sandbox_id"],
            state["generation"],
            state.get("source", "template"),
        )
        return path_to_vm

    def _stop_relay_process(self) -> None:
        relay, self._relay = self._relay, None
        if relay is not None and relay.poll() is None:
            relay.terminate()
            try:
                relay.wait(timeout=10)
            except subprocess.TimeoutExpired:
                relay.kill()
                relay.wait(timeout=5)
        for stream in self._relay_streams:
            stream.close()
        self._relay_streams.clear()

    def stop_emulator(self, path_to_vm: str, *args, **kwargs):
        if self._relay is None:
            return
        try:
            self._control("/stop", method="POST", timeout=30)
            self._relay.wait(timeout=30)
        except Exception as exc:
            logger.warning("Could not stop E2B relay cleanly: %s", exc)
        finally:
            self._stop_relay_process()
