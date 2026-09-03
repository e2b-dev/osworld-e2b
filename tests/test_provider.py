from __future__ import annotations

import dataclasses
import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

base = types.ModuleType("desktop_env.providers.base")
base.Provider = type("Provider", (), {})
sys.modules.setdefault("desktop_env", types.ModuleType("desktop_env"))
sys.modules.setdefault("desktop_env.providers", types.ModuleType("desktop_env.providers"))
sys.modules["desktop_env.providers.base"] = base

from realkit import provider  # noqa: E402
from realkit.ports import PortBundle, reserve_port_bundle  # noqa: E402

IMMUTABLE_REF = "osworld-gnome:62e8be41-4106-4850-96ea-afc822735b89"


class FakeProcess:
    def __init__(self, command, *, env, stdout, stderr):
        self.command = command
        self.env = env
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return 0

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9


def test_two_reservations_receive_disjoint_port_bundles() -> None:
    first = reserve_port_bundle()
    second = reserve_port_bundle()

    assert set(dataclasses.astuple(first)).isdisjoint(dataclasses.astuple(second))


def test_provider_starts_its_own_relay_and_reports_dynamic_endpoints(tmp_path: Path) -> None:
    bundle = PortBundle(control=31001, server=31002, chromium=31003, vlc=31004)
    processes = []
    controls = []

    def popen(*args, **kwargs):
        process = FakeProcess(*args, **kwargs)
        processes.append(process)
        return process

    def control(self, path, method="GET", timeout=300, payload=None):
        controls.append((path, method, payload))
        if path == "/health":
            return {"sandbox_id": "sandbox-1", "ready": True}
        return {"stopping": True, "sandbox_id": "sandbox-1"}

    with (
        patch.object(provider, "reserve_port_bundle", return_value=bundle),
        patch.object(provider.subprocess, "Popen", side_effect=popen),
        patch.object(provider.E2BProvider, "_control", control),
        patch.dict(
            provider.os.environ,
            {"E2B_ATTEMPT_DIR": str(tmp_path), "GUEST_TEMPLATE": IMMUTABLE_REF},
            clear=True,
        ),
    ):
        instance = provider.E2BProvider()
        instance.start_emulator(IMMUTABLE_REF, True, "Ubuntu")
        endpoints = instance.get_ip_address(IMMUTABLE_REF)
        instance.stop_emulator(IMMUTABLE_REF)

    assert endpoints == "127.0.0.1:31002:31003:0:31004"
    assert len(processes) == 1
    assert processes[0].env["E2B_RELAY_CONTROL_PORT"] == "31001"
    assert processes[0].env["E2B_RELAY_SERVER_PORT"] == "31002"
    assert processes[0].env["E2B_RELAY_CHROMIUM_PORT"] == "31003"
    assert processes[0].env["E2B_RELAY_VLC_PORT"] == "31004"
    assert processes[0].env["E2B_RELAY_EVENT_LOG"] == str(tmp_path / "relay-events.jsonl")
    assert processes[0].command[-1].endswith("e2b_relay.py")
    assert controls[-1][:2] == ("/stop", "POST")


def test_provider_start_is_idempotent_for_snapshot_restarts(tmp_path: Path) -> None:
    bundle = PortBundle(control=32001, server=32002, chromium=32003, vlc=32004)
    processes = []

    def popen(*args, **kwargs):
        process = FakeProcess(*args, **kwargs)
        processes.append(process)
        return process

    with (
        patch.object(provider, "reserve_port_bundle", return_value=bundle),
        patch.object(provider.subprocess, "Popen", side_effect=popen),
        patch.object(
            provider.E2BProvider,
            "_control",
            return_value={"sandbox_id": "sandbox-1", "ready": True},
        ),
        patch.dict(
            provider.os.environ,
            {"E2B_ATTEMPT_DIR": str(tmp_path), "GUEST_TEMPLATE": IMMUTABLE_REF},
            clear=True,
        ),
    ):
        instance = provider.E2BProvider()
        instance.start_emulator(IMMUTABLE_REF, True, "Ubuntu")
        instance.start_emulator(IMMUTABLE_REF, True, "Ubuntu")
        instance.stop_emulator(IMMUTABLE_REF)

    assert len(processes) == 1


def test_provider_control_payload_does_not_persist_in_relay_event_path(tmp_path: Path) -> None:
    bundle = PortBundle(control=33001, server=33002, chromium=33003, vlc=33004)
    captured_env = {}

    def popen(*args, **kwargs):
        captured_env.update(kwargs["env"])
        return FakeProcess(*args, **kwargs)

    with (
        patch.object(provider, "reserve_port_bundle", return_value=bundle),
        patch.object(provider.subprocess, "Popen", side_effect=popen),
        patch.object(
            provider.E2BProvider,
            "_control",
            return_value={"sandbox_id": "sandbox-1", "ready": True},
        ),
        patch.dict(
            provider.os.environ,
            {
                "E2B_ATTEMPT_DIR": str(tmp_path),
                "GUEST_TEMPLATE": IMMUTABLE_REF,
                "E2B_API_KEY": "secret-api-key",
            },
            clear=True,
        ),
    ):
        instance = provider.E2BProvider()
        instance.start_emulator(IMMUTABLE_REF, True, "Ubuntu")
        instance.stop_emulator(IMMUTABLE_REF)

    public = json.dumps(
        {
            "event_log": captured_env["E2B_RELAY_EVENT_LOG"],
            "ports": dataclasses.asdict(bundle),
        }
    )
    assert "secret-api-key" not in public


def test_relay_subprocess_does_not_inherit_model_credentials(tmp_path: Path) -> None:
    captured_env = {}

    def popen(*args, **kwargs):
        captured_env.update(kwargs["env"])
        return FakeProcess(*args, **kwargs)

    with (
        patch.object(provider.subprocess, "Popen", side_effect=popen),
        patch.object(
            provider.E2BProvider,
            "_control",
            return_value={"sandbox_id": "sandbox-1", "ready": True},
        ),
        patch.dict(
            provider.os.environ,
            {
                "E2B_ATTEMPT_DIR": str(tmp_path),
                "E2B_API_KEY": "e2b-secret",
                "OPENAI_API_KEY": "model-secret",
                "QWEN_ENDPOINT_0": "https://model.example/v1",
                "PATH": "/usr/bin",
            },
            clear=True,
        ),
    ):
        instance = provider.E2BProvider()
        instance.start_emulator(IMMUTABLE_REF, True, "Ubuntu")
        instance.stop_emulator(IMMUTABLE_REF)

    assert captured_env["E2B_API_KEY"] == "e2b-secret"
    assert captured_env["PATH"] == "/usr/bin"
    assert "OPENAI_API_KEY" not in captured_env
    assert "QWEN_ENDPOINT_0" not in captured_env
