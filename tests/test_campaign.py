from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from runner.campaign import execute_campaign

ROOT = Path(__file__).resolve().parents[1]
FAKE_RUNNER = ROOT / "tests" / "fixtures" / "fake_osworld_runner.py"
TEMPLATE = "osworld-gnome:62e8be41-4106-4850-96ea-afc822735b89"


def _inventory(task_ids: list[str]) -> dict:
    return {
        "profile": "fixture",
        "suite": "nogdrive",
        "inventory_sha256": "1" * 64,
        "task_count": len(task_ids),
        "tasks": [
            {"domain": "chrome", "id": task_id, "task_sha256": "2" * 64, "proxy": False}
            for task_id in task_ids
        ],
    }


@pytest.mark.asyncio
async def test_campaign_runs_in_parallel_and_accounts_for_all_tasks(tmp_path: Path) -> None:
    task_ids = [f"task-{index}" for index in range(12)]
    started = time.monotonic()

    ledger = await execute_campaign(
        python_executable=Path(sys.executable),
        run_root=tmp_path / "run",
        inventory=_inventory(task_ids),
        metadata={"profile": "fixture", "suite": "nogdrive", "template": TEMPLATE},
        runner=FAKE_RUNNER,
        osworld_root=tmp_path,
        template=TEMPLATE,
        num_envs=4,
        task_timeout_seconds=5,
        max_attempts=1,
        child_environment={"FAKE_DELAY_SECONDS": "0.2"},
    )
    elapsed = time.monotonic() - started
    aggregate = json.loads((ledger.root / "aggregate.json").read_text())

    assert aggregate["planned_tasks"] == 12
    assert aggregate["valid_tasks"] == 12
    assert aggregate["terminal_attempts"] == 12
    assert aggregate["missing_attempts"] == 0
    assert aggregate["max_observed_children"] == 4
    assert elapsed < 1.5


@pytest.mark.asyncio
async def test_campaign_preserves_distinct_invalid_outcomes_and_valid_zero(tmp_path: Path) -> None:
    outcomes = {
        "task-zero": "zero",
        "task-malformed": "malformed",
        "task-missing": "missing",
        "task-exit": "exit",
        "task-timeout": "timeout",
        "task-cleanup": "cleanup_failed",
    }
    ledger = await execute_campaign(
        python_executable=Path(sys.executable),
        run_root=tmp_path / "run",
        inventory=_inventory(list(outcomes)),
        metadata={"profile": "fixture", "suite": "nogdrive", "template": TEMPLATE},
        runner=FAKE_RUNNER,
        osworld_root=tmp_path,
        template=TEMPLATE,
        num_envs=3,
        task_timeout_seconds=0.2,
        max_attempts=1,
        child_environment={
            "FAKE_OUTCOMES": json.dumps(outcomes),
            "FAKE_TIMEOUT_SLEEP_SECONDS": "2",
        },
    )
    aggregate = ledger.aggregate()

    assert aggregate["valid_tasks"] == 1
    assert aggregate["reward_sum"] == 0.0
    assert aggregate["invalid_by_reason"] == {
        "cleanup_failed": 1,
        "malformed_result": 1,
        "missing_result": 1,
        "runner_exit": 1,
        "timeout": 1,
    }
    assert aggregate["missing_attempts"] == 0


@pytest.mark.asyncio
async def test_campaign_resume_appends_attempt_without_deleting_prior_evidence(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    inventory = _inventory(["task-a"])
    metadata = {"profile": "fixture", "suite": "nogdrive", "template": TEMPLATE}
    first = await execute_campaign(
        python_executable=Path(sys.executable),
        run_root=run_root,
        inventory=inventory,
        metadata=metadata,
        runner=FAKE_RUNNER,
        osworld_root=tmp_path,
        template=TEMPLATE,
        num_envs=1,
        task_timeout_seconds=2,
        max_attempts=1,
        child_environment={"FAKE_OUTCOMES": '{"task-a":"missing"}'},
    )
    first_attempt = run_root / "attempts" / "chrome" / "task-a" / "1"
    assert first_attempt.exists()

    second = await execute_campaign(
        python_executable=Path(sys.executable),
        run_root=run_root,
        inventory=inventory,
        metadata=metadata,
        runner=FAKE_RUNNER,
        osworld_root=tmp_path,
        template=TEMPLATE,
        num_envs=1,
        task_timeout_seconds=2,
        max_attempts=2,
        child_environment={"FAKE_OUTCOMES": '{"task-a":"success"}'},
    )

    assert first.fingerprint == second.fingerprint
    assert first_attempt.exists()
    assert (run_root / "attempts" / "chrome" / "task-a" / "2").exists()
    assert second.aggregate()["valid_tasks"] == 1
    assert len((run_root / "attempts.jsonl").read_text().splitlines()) == 6


@pytest.mark.asyncio
async def test_noop_resume_preserves_observed_parallelism(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    inventory = _inventory([f"task-{index}" for index in range(4)])
    metadata = {"profile": "fixture", "suite": "nogdrive", "template": TEMPLATE}
    kwargs = dict(
        python_executable=Path(sys.executable),
        run_root=run_root,
        inventory=inventory,
        metadata=metadata,
        runner=FAKE_RUNNER,
        osworld_root=tmp_path,
        template=TEMPLATE,
        num_envs=2,
        task_timeout_seconds=2,
        max_attempts=1,
        child_environment={"FAKE_DELAY_SECONDS": "0.05"},
    )

    await execute_campaign(**kwargs)
    first = json.loads((run_root / "aggregate.json").read_text())
    await execute_campaign(**kwargs)
    second = json.loads((run_root / "aggregate.json").read_text())

    assert first["max_observed_children"] == 2
    assert second == first


def test_default_parallelism_is_eight() -> None:
    from runner.campaign import DEFAULT_NUM_ENVS

    assert DEFAULT_NUM_ENVS == 8


def test_campaign_rejects_mutable_template_before_creating_run(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="immutable name:build_id"):
        import asyncio

        asyncio.run(
            execute_campaign(
                python_executable=Path(sys.executable),
                run_root=tmp_path / "run",
                inventory=_inventory(["task-a"]),
                metadata={"profile": "fixture"},
                runner=FAKE_RUNNER,
                osworld_root=tmp_path,
                template="osworld-gnome",
                num_envs=1,
                task_timeout_seconds=2,
                max_attempts=1,
            )
        )
    assert not (tmp_path / "run").exists()


@pytest.mark.asyncio
async def test_every_attempt_has_raw_logs_and_artifact_checksums(tmp_path: Path) -> None:
    ledger = await execute_campaign(
        python_executable=Path(sys.executable),
        run_root=tmp_path / "run",
        inventory=_inventory(["task-a"]),
        metadata={"profile": "fixture", "suite": "nogdrive", "template": TEMPLATE},
        runner=FAKE_RUNNER,
        osworld_root=tmp_path,
        template=TEMPLATE,
        num_envs=1,
        task_timeout_seconds=2,
        max_attempts=1,
    )
    attempt = ledger.root / "attempts" / "chrome" / "task-a" / "1"
    catalog = json.loads((attempt / "artifacts.json").read_text())
    paths = {item["path"] for item in catalog}

    assert {"stdout.log", "stderr.log", "task-manifest.json"}.issubset(paths)
    assert any(path.endswith("result.txt") for path in paths)
    assert any(path.endswith("relay-events.jsonl") for path in paths)


@pytest.mark.asyncio
async def test_campaign_injects_but_does_not_retain_secret_source_path_or_bytes(
    tmp_path: Path,
) -> None:
    secret = tmp_path / "google-service-account.json"
    secret.write_text('{"private_key":"secret-private-key"}')
    inventory = _inventory(["task-a"])

    ledger = await execute_campaign(
        python_executable=Path(sys.executable),
        run_root=tmp_path / "run",
        inventory=inventory,
        metadata={"profile": "fixture", "suite": "gdrive", "template": TEMPLATE},
        runner=FAKE_RUNNER,
        osworld_root=tmp_path,
        template=TEMPLATE,
        num_envs=1,
        task_timeout_seconds=2,
        max_attempts=1,
        secret_mounts=[f"{secret}:/opt/osworld/secrets/google.json"],
    )
    retained = (ledger.root / "run.json").read_text() + (
        ledger.root / "attempts" / "chrome" / "task-a" / "1" / "stdout.log"
    ).read_text()

    assert str(secret) not in retained
    assert "secret-private-key" not in retained
    assert "google-service-account.json" in retained
    assert "/opt/osworld/secrets/google.json" in retained


@pytest.mark.asyncio
async def test_campaign_redacts_secrets_supplied_in_child_environment(tmp_path: Path) -> None:
    secret = "fireworks-secret-value"
    ledger = await execute_campaign(
        python_executable=Path(sys.executable),
        run_root=tmp_path / "run",
        inventory=_inventory(["task-a"]),
        metadata={"profile": "fixture", "suite": "nogdrive", "template": TEMPLATE},
        runner=FAKE_RUNNER,
        osworld_root=tmp_path,
        template=TEMPLATE,
        num_envs=1,
        task_timeout_seconds=2,
        max_attempts=1,
        child_environment={
            "ANTHROPIC_API_KEY": secret,
            "FAKE_ECHO_ENV": "1",
            "FAKE_WRITE_SECRET_ARTIFACT": "1",
        },
    )
    stdout = (ledger.root / "attempts" / "chrome" / "task-a" / "1" / "stdout.log").read_text()

    assert secret not in stdout
    assert "<redacted>" in stdout
    args_snapshot = next(ledger.root.rglob("args.json")).read_text()
    assert secret not in args_snapshot
    assert "<redacted>" in args_snapshot


@pytest.mark.asyncio
async def test_campaign_adds_osworld_root_to_child_pythonpath(tmp_path: Path) -> None:
    osworld_root = tmp_path / "OSWorld"
    osworld_root.mkdir()
    ledger = await execute_campaign(
        python_executable=Path(sys.executable),
        run_root=tmp_path / "run",
        inventory=_inventory(["task-a"]),
        metadata={"profile": "fixture", "suite": "nogdrive", "template": TEMPLATE},
        runner=FAKE_RUNNER,
        osworld_root=osworld_root,
        template=TEMPLATE,
        num_envs=1,
        task_timeout_seconds=2,
        max_attempts=1,
        child_environment={
            "FAKE_ECHO_PYTHONPATH": "1",
            "PYTHONPATH": "/existing/pythonpath",
        },
    )
    stdout = (ledger.root / "attempts" / "chrome" / "task-a" / "1" / "stdout.log").read_text()

    assert f"PYTHONPATH {osworld_root}:/existing/pythonpath" in stdout


@pytest.mark.asyncio
async def test_campaign_launches_children_with_the_declared_python_interpreter(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "interpreter-used"
    interpreter = tmp_path / "python"
    interpreter.write_text(
        f"#!/bin/sh\nprintf launched > '{marker}'\nexec '{sys.executable}' \"$@\"\n"
    )
    interpreter.chmod(0o755)

    await execute_campaign(
        python_executable=interpreter,
        run_root=tmp_path / "run",
        inventory=_inventory(["task-a"]),
        metadata={"profile": "fixture", "suite": "nogdrive", "template": TEMPLATE},
        runner=FAKE_RUNNER,
        osworld_root=tmp_path,
        template=TEMPLATE,
        num_envs=1,
        task_timeout_seconds=2,
        max_attempts=1,
    )

    assert marker.read_text() == "launched"


@pytest.mark.asyncio
async def test_campaign_rejects_interpreter_identity_drift_on_resume(tmp_path: Path) -> None:
    first_interpreter = tmp_path / "python-first"
    second_interpreter = tmp_path / "python-second"
    first_interpreter.symlink_to(sys.executable)
    second_interpreter.symlink_to(sys.executable)
    kwargs = {
        "run_root": tmp_path / "run",
        "inventory": _inventory(["task-a"]),
        "metadata": {"profile": "fixture", "suite": "nogdrive", "template": TEMPLATE},
        "runner": FAKE_RUNNER,
        "osworld_root": tmp_path,
        "template": TEMPLATE,
        "num_envs": 1,
        "task_timeout_seconds": 2,
        "max_attempts": 1,
    }
    await execute_campaign(python_executable=first_interpreter, **kwargs)

    with pytest.raises(ValueError, match="campaign identity differs"):
        await execute_campaign(python_executable=second_interpreter, **kwargs)
