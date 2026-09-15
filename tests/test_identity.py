from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from realkit import manager, relay

IMMUTABLE_REF = "osworld-gnome:62e8be41-4106-4850-96ea-afc822735b89"
ROOT = Path(__file__).resolve().parents[1]


def test_manager_requires_an_explicit_template_reference() -> None:
    with patch.dict(os.environ, {}, clear=True), pytest.raises(ValueError, match="GUEST_TEMPLATE"):
        manager.E2BVMManager().get_vm_path()


def test_manager_rejects_a_mutable_template_alias() -> None:
    with (
        patch.dict(os.environ, {"GUEST_TEMPLATE": "osworld-gnome"}, clear=True),
        pytest.raises(ValueError, match="immutable name:build_id"),
    ):
        manager.E2BVMManager().get_vm_path()


def test_manager_returns_an_immutable_template_reference() -> None:
    with patch.dict(os.environ, {"GUEST_TEMPLATE": IMMUTABLE_REF}, clear=True):
        assert manager.E2BVMManager().get_vm_path() == IMMUTABLE_REF


@pytest.mark.asyncio
async def test_relay_rejects_mutable_identity_before_creating_a_sandbox() -> None:
    guest_manager = relay.GuestManager()
    with (
        patch.object(relay, "TEMPLATE", "osworld-gnome"),
        patch.object(relay, "Sandbox") as sandbox,
        patch.object(guest_manager, "_wait_ready", AsyncMock()),
        pytest.raises(ValueError, match="immutable name:build_id"),
    ):
        await guest_manager.replace()

    sandbox.create.assert_not_called()


def test_normal_runner_delegates_identity_validation_to_the_contract(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    python = fake_bin / "python3"
    python.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGS_LOG"\nexit 77\n')
    python.chmod(0o755)
    args_log = tmp_path / "args.log"

    result = subprocess.run(
        ["bash", str(ROOT / "runner" / "run.sh"), "--contract", "contract.json"],
        env={
            **os.environ,
            "ARGS_LOG": str(args_log),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 77
    assert args_log.read_text().splitlines()[-2:] == ["--contract", "contract.json"]


@pytest.mark.asyncio
async def test_stop_control_is_idempotent_without_a_running_guest() -> None:
    event = asyncio.Event()
    with (
        patch.object(relay, "manager", relay.GuestManager()),
        patch.object(relay, "stop_event", event),
    ):
        response = await relay.stop(None)

    assert event.is_set()
    assert response.status == 200
    assert response.text == '{"stopping": true, "sandbox_id": null}'
