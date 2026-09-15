#!/usr/bin/env python3
"""Run the published MiniMax M3 parity sample on isolated E2B sandboxes."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import signal
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from runner.campaign import DEFAULT_NUM_ENVS, execute_campaign
from runner.runtime import inspect_runtime

FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference"
FIREWORKS_MODEL = "accounts/fireworks/models/minimax-m3"
M3_RUNNER = "scripts/python/run_multienv_m3.py"


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def build_sample_inventory(inventory: dict, reference: dict) -> dict:
    """Resolve the reference sample against the exact pinned inventory."""
    available = {(item["domain"], item["id"]): item for item in inventory["tasks"]}
    selected = []
    for expected in reference["sample"]["tasks"]:
        key = (expected["domain"], expected["id"])
        actual = available.get(key)
        if actual is None:
            raise ValueError(f"reference task is absent from pinned inventory: {key}")
        if actual["task_sha256"] != expected["task_sha256"]:
            raise ValueError(f"reference task content drift: {key}")
        if actual.get("proxy"):
            raise ValueError(f"sample unexpectedly requires a proxy: {key}")
        selected.append(actual)
    if len(selected) != reference["sample"]["task_count"]:
        raise ValueError("reference sample task count is inconsistent")
    return {
        "profile": inventory["profile"],
        "suite": inventory["suite"],
        "source_inventory_sha256": inventory["inventory_sha256"],
        "inventory_sha256": _canonical_sha256(selected),
        "task_count": len(selected),
        "tasks": selected,
    }


def build_comparison(results: dict[tuple[str, str], float], reference: dict) -> dict:
    """Compare valid E2B task rewards with the archived public task rewards."""
    rows = []
    agreements = 0
    for expected in reference["sample"]["tasks"]:
        key = (expected["domain"], expected["id"])
        actual = results.get(key)
        agrees = actual is not None and math.isclose(
            actual, float(expected["published_reward"]), abs_tol=1e-12
        )
        agreements += int(agrees)
        rows.append(
            {
                "domain": key[0],
                "task_id": key[1],
                "published_reward": float(expected["published_reward"]),
                "e2b_reward": actual,
                "agrees": agrees if actual is not None else None,
            }
        )
    ready = len(results) == len(rows) and all(row["e2b_reward"] is not None for row in rows)
    e2b_score = sum(results.values()) / len(rows) if ready else None
    published_sample_score = float(reference["sample"]["score"])
    return {
        "schema_version": 1,
        "ready": ready,
        "valid_tasks": len(results),
        "required_tasks": len(rows),
        "published_full_score": float(reference["public_run"]["score"]),
        "published_sample_score": published_sample_score,
        "e2b_sample_score": e2b_score,
        "absolute_sample_score_delta": (
            abs(e2b_score - published_sample_score) if e2b_score is not None else None
        ),
        "task_reward_agreements": agreements,
        "task_reward_agreement_rate": agreements / len(rows),
        "interpretation": "environment_validation_sample_not_full_benchmark_estimate",
        "tasks": rows,
    }


def _run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"minimax-m3-{timestamp}-{uuid.uuid4().hex[:8]}"


def _git_head(root: Path) -> str:
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()


def _default_template(root: Path) -> str:
    document = json.loads((root / "results/template-build.json").read_text())
    return document["immutableRef"]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reference",
        type=Path,
        default=root / "validation/reference/minimax-m3-osworld-verified-sample.json",
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        default=root / "validation/inventories/current-v1-nogdrive.json",
    )
    parser.add_argument("--osworld-root", type=Path, default=root / "runner" / "OSWorld")
    parser.add_argument("--python-executable", type=Path, default=None)
    parser.add_argument("--result-root", type=Path, default=root / "results/runs")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--template", default=None)
    parser.add_argument("--num-envs", type=int, default=DEFAULT_NUM_ENVS)
    parser.add_argument("--task-timeout-seconds", type=float, default=3600)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()

    try:
        reference = json.loads(args.reference.read_text())
        inventory = json.loads(args.inventory.read_text())
        sample = build_sample_inventory(inventory, reference)
        osworld_root = args.osworld_root.resolve()
        expected_commit = reference["reproduction"]["osworld_commit"]
        if _git_head(osworld_root) != expected_commit:
            raise ValueError("OSWorld checkout does not match the reference reproduction commit")
        runner = osworld_root / M3_RUNNER
        if not runner.is_file():
            raise ValueError(f"patched M3 runner is missing: {runner}")
        python_executable = args.python_executable or osworld_root / ".venv" / "bin" / "python"
        runtime = inspect_runtime(
            python_executable=python_executable,
            osworld_root=osworld_root,
            runner=runner,
            expected_commit=expected_commit,
        )
        template = args.template or _default_template(root)
        upstream_args = (
            "--base_url",
            FIREWORKS_BASE_URL,
            "--model",
            FIREWORKS_MODEL,
            "--observation_type",
            "screenshot",
            "--action_space",
            "pyautogui",
            "--sleep_after_execution",
            "3",
            "--max_steps",
            "100",
            "--max_trajectory_length",
            "10",
            "--temperature",
            "1",
            "--max_tokens",
            "8192",
            "--coordinate_type",
            "relative",
            "--screen_width",
            "1920",
            "--screen_height",
            "1080",
            "--client_password",
            "password",
            "--env_start_delay",
            "0",
        )
        preflight = {
            "profile": sample["profile"],
            "suite": sample["suite"],
            "task_count": sample["task_count"],
            "domains": [item["domain"] for item in sample["tasks"]],
            "osworld_commit": expected_commit,
            "template": template,
            "model": FIREWORKS_MODEL,
            "num_envs": args.num_envs,
            "runtime": runtime,
            "fireworks_api_key_available": bool(os.environ.get("FIREWORKS_API_KEY")),
        }
        if args.preflight_only:
            print("PREFLIGHT_OK", json.dumps(preflight, sort_keys=True))
            return 0
        api_key = os.environ.get("FIREWORKS_API_KEY")
        if not api_key:
            raise ValueError("FIREWORKS_API_KEY is required for MiniMax M3 execution")
        metadata = {
            **preflight,
            "reference_sha256": hashlib.sha256(args.reference.read_bytes()).hexdigest(),
            "source_inventory_sha256": sample["source_inventory_sha256"],
            "sample_inventory_sha256": sample["inventory_sha256"],
            "runner": M3_RUNNER,
            "upstream_args": list(upstream_args),
            "max_attempts": args.max_attempts,
            "task_timeout_seconds": args.task_timeout_seconds,
        }
        metadata.pop("fireworks_api_key_available")
        run_root = args.result_root / (args.run_id or _run_id())
        ledger = None
        for _ in range(args.max_attempts):
            ledger = asyncio.run(
                execute_campaign(
                    python_executable=python_executable,
                    run_root=run_root,
                    inventory=sample,
                    metadata=metadata,
                    runner=runner,
                    osworld_root=osworld_root,
                    template=template,
                    num_envs=args.num_envs,
                    task_timeout_seconds=args.task_timeout_seconds,
                    max_attempts=args.max_attempts,
                    upstream_args=upstream_args,
                    child_environment={
                        "ANTHROPIC_API_KEY": api_key,
                        "ANTHROPIC_BASE_URL": FIREWORKS_BASE_URL,
                        "ANTHROPIC_MODEL": FIREWORKS_MODEL,
                        "M3_THINKING_MODE": "",
                    },
                )
            )
            if not ledger.resume_candidates(args.max_attempts):
                break
        assert ledger is not None
        results = {
            (task.domain, task.id): reward for task, reward in ledger.valid_results().items()
        }
        comparison = build_comparison(results, reference)
        _write_json(run_root / "comparison.json", comparison)
        aggregate = ledger.refresh_aggregate(
            **{
                key: value
                for key, value in json.loads((run_root / "aggregate.json").read_text()).items()
                if key in {"configured_num_envs", "max_observed_children"}
            },
            comparison=comparison,
        )
    except (OSError, ValueError, subprocess.CalledProcessError, KeyboardInterrupt) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"run_root": str(run_root), "aggregate": aggregate}, sort_keys=True))
    return 0 if aggregate["remaining_tasks"] == 0 else 1


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.default_int_handler)
    raise SystemExit(main())
