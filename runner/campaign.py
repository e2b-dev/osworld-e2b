#!/usr/bin/env python3
"""Parallel, resumable OSWorld campaign coordinator for E2B."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import signal
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from realkit.e2b_policy import require_immutable_template_ref
from realkit.results import AttemptEvent, RunLedger, TaskKey, catalog_artifacts
from runner.profile import load_inventory, select_profile

DEFAULT_NUM_ENVS = 8
PROTECTED_ARGUMENTS = {
    "--provider_name",
    "--path_to_vm",
    "--headless",
    "--test_all_meta_path",
    "--result_dir",
    "--num_envs",
}


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _cleanup_status(path: Path) -> str:
    if not path.exists():
        return "not_observed"
    try:
        events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError):
        return "malformed"
    if any(event.get("event") == "SANDBOX_CLEANUP_FAILED" for event in events):
        return "failed"
    created = {
        event["sandbox_id"]
        for event in events
        if event.get("event") == "SANDBOX_CREATED" and event.get("sandbox_id")
    }
    cleaned = {
        event["sandbox_id"]
        for event in events
        if event.get("event") == "SANDBOX_CLEANED" and event.get("sandbox_id")
    }
    if cleaned and (not created or created.issubset(cleaned)):
        return "success"
    return "not_observed"


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()


def _parse_reward(result_root: Path) -> tuple[float | None, str | None]:
    result_files = list(result_root.rglob("result.txt"))
    if not result_files:
        return None, "missing_result"
    if len(result_files) != 1:
        return None, "identity_drift"
    try:
        reward = float(result_files[0].read_text().strip())
    except (OSError, ValueError):
        return None, "malformed_result"
    if not math.isfinite(reward):
        return None, "malformed_result"
    return reward, None


async def execute_campaign(
    *,
    run_root: Path,
    inventory: dict,
    metadata: dict,
    runner: Path,
    osworld_root: Path,
    template: str,
    num_envs: int = DEFAULT_NUM_ENVS,
    task_timeout_seconds: float,
    max_attempts: int,
    upstream_args: tuple[str, ...] | list[str] = (),
    child_environment: dict[str, str] | None = None,
) -> RunLedger:
    template = require_immutable_template_ref(template, "template")
    if num_envs < 1:
        raise ValueError("num_envs must be positive")
    if task_timeout_seconds <= 0:
        raise ValueError("task_timeout_seconds must be positive")
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    protected = PROTECTED_ARGUMENTS.intersection(upstream_args)
    if protected:
        raise ValueError(f"upstream arguments override campaign identity: {sorted(protected)}")
    tasks = [TaskKey(item["domain"], item["id"]) for item in inventory["tasks"]]
    run_root = Path(run_root)
    if (run_root / "run.json").exists():
        ledger = RunLedger.open(run_root)
        if ledger.document["metadata"] != metadata or list(ledger.tasks) != tasks:
            raise ValueError("campaign identity differs from the existing run")
    else:
        ledger = RunLedger.create(run_root, metadata=metadata, tasks=tasks)

    runner = Path(runner).resolve()
    osworld_root = Path(osworld_root).resolve()
    semaphore = asyncio.Semaphore(num_envs)
    counter_lock = asyncio.Lock()
    active_children = 0
    max_observed_children = 0

    async def run_attempt(task: TaskKey, attempt: int) -> None:
        nonlocal active_children, max_observed_children
        async with semaphore:
            attempt_dir = run_root / "attempts" / task.domain / task.id / str(attempt)
            attempt_dir.mkdir(parents=True, exist_ok=True)
            relative_attempt_dir = attempt_dir.relative_to(run_root).as_posix()
            ledger.append(AttemptEvent.planned(task, attempt, relative_attempt_dir))
            task_manifest = attempt_dir / "task-manifest.json"
            result_root = attempt_dir / "upstream-results"
            log_root = attempt_dir / "upstream-logs"
            result_root.mkdir()
            log_root.mkdir()
            _write_json(task_manifest, {task.domain: [task.id]})
            command = [
                sys.executable,
                str(runner),
                "--provider_name",
                "e2b",
                "--path_to_vm",
                template,
                "--headless",
                "--test_all_meta_path",
                str(task_manifest),
                "--result_dir",
                str(result_root),
                "--num_envs",
                "1",
                *upstream_args,
            ]
            environment = {
                **os.environ,
                **(child_environment or {}),
                "GUEST_TEMPLATE": template,
                "E2B_ATTEMPT_DIR": str(attempt_dir),
                "E2B_RELAY_PATH": str(osworld_root / "e2b_relay.py"),
                "OSWORLD_LOG_DIR": str(log_root),
            }
            stdout_path = attempt_dir / "stdout.log"
            stderr_path = attempt_dir / "stderr.log"
            timed_out = False
            interrupted = False
            process = None
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=osworld_root,
                    env=environment,
                    stdout=stdout,
                    stderr=stderr,
                )
                ledger.append(AttemptEvent.started(task, attempt, pid=process.pid))
                async with counter_lock:
                    active_children += 1
                    max_observed_children = max(max_observed_children, active_children)
                try:
                    await asyncio.wait_for(process.wait(), timeout=task_timeout_seconds)
                except asyncio.TimeoutError:
                    timed_out = True
                    await _terminate(process)
                except asyncio.CancelledError:
                    interrupted = True
                    await _terminate(process)
                finally:
                    async with counter_lock:
                        active_children -= 1

            cleanup = _cleanup_status(attempt_dir / "relay-events.jsonl")
            reward, result_error = _parse_reward(result_root)
            artifacts = catalog_artifacts(attempt_dir)
            _write_json(attempt_dir / "artifacts.json", artifacts)
            if interrupted:
                ledger.append(
                    AttemptEvent.invalid(
                        task, attempt, "interrupted", cleanup=cleanup, artifacts=artifacts
                    )
                )
                raise asyncio.CancelledError
            if timed_out:
                ledger.append(
                    AttemptEvent.invalid(
                        task, attempt, "timeout", cleanup=cleanup, artifacts=artifacts
                    )
                )
            elif process is None or process.returncode != 0:
                ledger.append(
                    AttemptEvent.invalid(
                        task, attempt, "runner_exit", cleanup=cleanup, artifacts=artifacts
                    )
                )
            elif result_error is not None:
                ledger.append(
                    AttemptEvent.invalid(
                        task, attempt, result_error, cleanup=cleanup, artifacts=artifacts
                    )
                )
            elif cleanup != "success":
                ledger.append(
                    AttemptEvent.invalid(
                        task, attempt, "cleanup_failed", cleanup=cleanup, artifacts=artifacts
                    )
                )
            else:
                ledger.append(
                    AttemptEvent.valid(
                        task,
                        attempt,
                        reward=reward,
                        cleanup=cleanup,
                        artifacts=artifacts,
                    )
                )

    candidates = ledger.resume_candidates(max_attempts)
    campaign_tasks = [
        asyncio.create_task(run_attempt(task, attempt)) for task, attempt in candidates
    ]
    try:
        await asyncio.gather(*campaign_tasks)
    except BaseException:
        for campaign_task in campaign_tasks:
            campaign_task.cancel()
        await asyncio.gather(*campaign_tasks, return_exceptions=True)
        ledger.refresh_aggregate(
            configured_num_envs=num_envs,
            max_observed_children=max_observed_children,
        )
        raise
    ledger.refresh_aggregate(
        configured_num_envs=num_envs,
        max_observed_children=max_observed_children,
    )
    return ledger


def _run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="current-v1")
    parser.add_argument("--suite", default="nogdrive")
    parser.add_argument("--template", required=True)
    parser.add_argument("--osworld-root", type=Path, default=root / "runner" / "OSWorld")
    parser.add_argument("--result-root", type=Path, default=root / "results" / "runs")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--runner", type=Path, default=None)
    parser.add_argument("--num-envs", type=int, default=DEFAULT_NUM_ENVS)
    parser.add_argument("--task-timeout-seconds", type=float, default=1800)
    parser.add_argument("--max-attempts", type=int, default=1)
    args, upstream_args = parser.parse_known_args()
    if upstream_args and upstream_args[0] == "--":
        upstream_args = upstream_args[1:]
    try:
        profiles_path = root / "validation" / "profiles.json"
        profile = select_profile(args.profile, profiles_path)
        if args.suite not in profile["suites"]:
            raise ValueError(f"profile {args.profile} does not declare suite {args.suite}")
        inventory = load_inventory(root / profile["suites"][args.suite]["inventory"])
        runner = args.runner or args.osworld_root / profile["runner"]
        metadata = {
            "profile": args.profile,
            "suite": args.suite,
            "osworld_commit": profile["commit"],
            "inventory_sha256": inventory["inventory_sha256"],
            "template": args.template,
            "runner": profile["runner"],
            "upstream_args": upstream_args,
        }
        run_root = args.result_root / (args.run_id or _run_id())
        ledger = asyncio.run(
            execute_campaign(
                run_root=run_root,
                inventory=inventory,
                metadata=metadata,
                runner=runner,
                osworld_root=args.osworld_root,
                template=args.template,
                num_envs=args.num_envs,
                task_timeout_seconds=args.task_timeout_seconds,
                max_attempts=args.max_attempts,
                upstream_args=upstream_args,
            )
        )
    except (OSError, ValueError, KeyboardInterrupt) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"run_root": str(ledger.root), "aggregate": ledger.aggregate()}))
    return 0 if ledger.aggregate()["remaining_tasks"] == 0 else 1


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.default_int_handler)
    raise SystemExit(main())
