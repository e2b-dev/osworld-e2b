#!/usr/bin/env python3
"""No-agent OSWorld environment-path validation for the E2B provider.

This exercises reset/setup, screenshot and accessibility observations, one
pyautogui action, and the configured evaluator. A PATH_PASS is not a benchmark
task pass; the evaluator score is recorded separately.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import signal
import subprocess
import sys
import traceback
import types
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen


def _stub(name: str, package: bool = False) -> None:
    module = types.ModuleType(name)
    if package:
        module.__path__ = []
    module.__getattr__ = lambda attr: type(attr, (), {})
    sys.modules[name] = module


for dependency in ["pyautogui"]:
    _stub(dependency)
for dependency in [
    "easyocr",
    "librosa",
    "acoustid",
    "borb",
    "borb.pdf",
    "pydrive",
    "pydrive.auth",
    "pydrive.drive",
    "fastdtw",
]:
    _stub(dependency, package=True)

from desktop_env.desktop_env import DesktopEnv  # noqa: E402


class TaskTimeout(BaseException):
    pass


def _alarm_handler(_signum, _frame):
    raise TaskTimeout("per-task wall-clock limit exceeded")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def relay_state() -> dict:
    with urlopen("http://127.0.0.1:14999/state", timeout=10) as response:
        return json.load(response)


def osworld_commit(root: Path) -> str:
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()


def classify(stage: str, error: BaseException) -> tuple[str, str]:
    detail = f"{type(error).__name__}: {error}"
    low = detail.lower()
    if isinstance(error, TaskTimeout):
        return "task-timeout", detail
    if any(word in low for word in ("cdp", "playwright", "websocket", "connect_over_cdp")):
        return "chrome-cdp", detail
    if any(word in low for word in ("connection", "timed out", "max retries", "502", "504")):
        return "transport", detail
    return f"environment/{stage}", detail


def load_tasks(root: Path, manifest_path: Path) -> tuple[dict, list[tuple[dict, Path]]]:
    manifest = json.loads(manifest_path.read_text())
    tasks = []
    for item in manifest["tasks"]:
        path = root / "evaluation_examples" / "examples" / item["domain"] / f"{item['id']}.json"
        if not path.is_file():
            raise FileNotFoundError(f"manifest task does not exist at pinned checkout: {path}")
        tasks.append((item, path))
    return manifest, tasks


def run_task(env: DesktopEnv, item: dict, task_path: Path) -> dict:
    task = json.loads(task_path.read_text())
    record = {
        "id": task["id"],
        "domain": item["domain"],
        "related_apps": task.get("related_apps"),
        "evaluator": task.get("evaluator", {}).get("func"),
        "started_at": utc_now(),
        "stage": "reset",
        "path_status": None,
        "score": None,
    }
    try:
        observation = env.reset(task_config=task)
        state = relay_state()
        record["sandbox"] = {
            "id": state["sandbox_id"],
            "generation": state["generation"],
            "restricted_ingress": state["restricted_ingress"],
        }
        screenshot = observation.get("screenshot")
        accessibility = env.controller.get_accessibility_tree()
        if not screenshot:
            raise RuntimeError("OSWorld returned an empty screenshot observation")
        if not accessibility:
            raise RuntimeError("OSWorld returned an empty accessibility tree")
        record["observation"] = {
            "screenshot_bytes": len(screenshot),
            "accessibility_characters": len(accessibility),
        }

        record["stage"] = "step"
        env.step("import pyautogui; pyautogui.moveTo(300, 300); pyautogui.press('esc')", pause=1)

        record["stage"] = "evaluate"
        score = env.evaluate()
        record["score"] = float(score)
        record["path_status"] = "PATH_PASS"
        record["stage"] = "complete"
    except BaseException as error:
        cause, detail = classify(record["stage"], error)
        record.update(path_status="PATH_FAIL", cause=cause, detail=detail)
        record["trace_tail"] = traceback.format_exc()[-1000:]
    record["finished_at"] = utc_now()
    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--osworld-root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task-timeout-seconds", type=int, default=900)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.osworld_root.resolve()
    manifest, tasks = load_tasks(root, args.manifest.resolve())
    expected_commit = manifest["osworld_commit"]
    actual_commit = osworld_commit(root)
    if actual_commit != expected_commit:
        raise RuntimeError(
            f"OSWorld commit mismatch: expected {expected_commit}, got {actual_commit}"
        )
    # Several upstream getters/evaluators still resolve assets relative to the
    # checkout. validate.sh also changes directory before import so import-time
    # settings follow the same rule; keep this here for direct harness use.
    os.chdir(root)

    run = {
        "schema_version": 1,
        "run_id": str(uuid.uuid4()),
        "started_at": utc_now(),
        "purpose": "environment-path validation; not an agent benchmark score",
        "osworld_commit": actual_commit,
        "manifest": manifest,
        "host": {"python": platform.python_version(), "platform": platform.platform()},
        "dependencies": {name: importlib.metadata.version(name) for name in ("e2b", "aiohttp")},
        "relay": relay_state(),
        "records": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    jsonl_path = args.output.with_suffix(".jsonl")
    jsonl_path.write_text("")

    signal.signal(signal.SIGALRM, _alarm_handler)
    env = None
    try:
        env = DesktopEnv(
            provider_name="e2b",
            os_type="Ubuntu",
            action_space="pyautogui",
            require_a11y_tree=False,
            require_terminal=False,
            screen_size=(1920, 1080),
            headless=True,
            enable_proxy=False,
        )
        sandbox_ids = set()
        for item, task_path in tasks:
            signal.alarm(args.task_timeout_seconds)
            try:
                record = run_task(env, item, task_path)
            finally:
                signal.alarm(0)
            run["records"].append(record)
            if record.get("sandbox"):
                sandbox_id = record["sandbox"]["id"]
                record["sandbox"]["unique_in_run"] = sandbox_id not in sandbox_ids
                sandbox_ids.add(sandbox_id)
            with jsonl_path.open("a") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
            print(json.dumps(record, sort_keys=True), file=sys.stderr)
    finally:
        if env is not None:
            env.close()

    run["finished_at"] = utc_now()
    run["summary"] = {
        "tasks": len(run["records"]),
        "path_passes": sum(r["path_status"] == "PATH_PASS" for r in run["records"]),
        "path_failures": sum(r["path_status"] == "PATH_FAIL" for r in run["records"]),
        "unique_sandboxes": len(
            {r.get("sandbox", {}).get("id") for r in run["records"] if r.get("sandbox")}
        ),
        "all_recorded_sandboxes_unique": all(
            r.get("sandbox", {}).get("unique_in_run", False) for r in run["records"]
        ),
    }
    args.output.write_text(json.dumps(run, indent=2, sort_keys=True) + "\n")
    print(json.dumps(run["summary"], sort_keys=True))
    return 0 if run["summary"]["path_failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
