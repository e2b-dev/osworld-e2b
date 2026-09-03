#!/usr/bin/env python3
"""Deterministic stand-in for an OSWorld runner used by offline campaign tests."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def main() -> int:
    print("ARGS", " ".join(sys.argv))
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider_name")
    parser.add_argument("--path_to_vm")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--test_all_meta_path", type=Path)
    parser.add_argument("--result_dir", type=Path)
    parser.add_argument("--num_envs")
    args, _ = parser.parse_known_args()
    manifest = json.loads(args.test_all_meta_path.read_text())
    domain = next(iter(manifest))
    task_id = manifest[domain][0]
    outcome = json.loads(os.environ.get("FAKE_OUTCOMES", "{}")).get(task_id, "success")
    delay = float(os.environ.get("FAKE_DELAY_SECONDS", "0"))
    if outcome == "timeout":
        time.sleep(float(os.environ.get("FAKE_TIMEOUT_SLEEP_SECONDS", "5")))
    else:
        time.sleep(delay)

    attempt_dir = Path(os.environ["E2B_ATTEMPT_DIR"])
    relay_events = attempt_dir / "relay-events.jsonl"
    relay_events.parent.mkdir(parents=True, exist_ok=True)
    cleanup = "failed" if outcome == "cleanup_failed" else "success"
    event = "SANDBOX_CLEANUP_FAILED" if cleanup == "failed" else "SANDBOX_CLEANED"
    relay_events.write_text(
        json.dumps({"event": event, "sandbox_id": f"sandbox-{task_id}", "cleanup": cleanup}) + "\n"
    )

    output = args.result_dir / "pyautogui" / "screenshot" / "fake" / domain / task_id
    output.mkdir(parents=True, exist_ok=True)
    (output / "traj.jsonl").write_text(json.dumps({"task": task_id}) + "\n")
    if outcome in {"success", "cleanup_failed"}:
        (output / "result.txt").write_text("0.5\n")
    elif outcome == "zero":
        (output / "result.txt").write_text("0\n")
    elif outcome == "malformed":
        (output / "result.txt").write_text("not-a-score\n")
    elif outcome == "exit":
        print(f"forced failure for {task_id}", file=sys.stderr)
        return 7
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
