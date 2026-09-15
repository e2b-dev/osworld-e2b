#!/usr/bin/env python3
"""Inspect and validate the pinned OSWorld execution runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    from runner.patch_upstream import TRANSFORMS, verify_patched_checkout
except ModuleNotFoundError:
    from patch_upstream import TRANSFORMS, verify_patched_checkout

RUNTIME_PROBE = """
import importlib.metadata
import json
import platform

print(json.dumps({
    "python": platform.python_version(),
    "anthropic": importlib.metadata.version("anthropic"),
    "e2b": importlib.metadata.version("e2b"),
}, sort_keys=True))
"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head(root: Path) -> str:
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()


def inspect_runtime(
    *,
    python_executable: Path,
    osworld_root: Path,
    runner: Path,
    expected_commit: str,
    contract_path: Path | None = None,
) -> dict[str, object]:
    """Return exact runtime identity after enforcing the supported contract."""
    python_executable = Path(os.path.abspath(python_executable))
    osworld_root = Path(osworld_root).resolve()
    if not python_executable.is_file() or not os.access(python_executable, os.X_OK):
        raise ValueError(f"OSWorld Python is not executable: {python_executable}")
    if not (osworld_root / ".git").exists():
        raise ValueError(f"OSWorld root is not a Git checkout: {osworld_root}")
    actual_commit = _git_head(osworld_root)
    if actual_commit != expected_commit:
        raise ValueError(
            f"OSWorld commit mismatch: expected {expected_commit}, got {actual_commit}"
        )
    runner_path = Path(runner)
    if not runner_path.is_absolute():
        runner_path = osworld_root / runner_path
    runner_path = runner_path.resolve()
    try:
        runner_relative = runner_path.relative_to(osworld_root).as_posix()
    except ValueError as error:
        raise ValueError("runner must be inside the OSWorld checkout") from error
    if not runner_path.is_file():
        raise ValueError(f"OSWorld runner is missing: {runner_path}")
    if runner_relative in TRANSFORMS:
        verify_patched_checkout(osworld_root, expected_commit)
    lock_path = osworld_root / "uv.lock"
    if not lock_path.is_file():
        raise ValueError(f"OSWorld lock is missing: {lock_path}")
    pinned_lock = subprocess.check_output(["git", "-C", str(osworld_root), "show", "HEAD:uv.lock"])
    if lock_path.read_bytes() != pinned_lock:
        raise ValueError("OSWorld lock differs from the pinned commit")

    raw = subprocess.check_output(
        [str(python_executable), "-c", RUNTIME_PROBE], text=True, stderr=subprocess.STDOUT
    )
    observed = json.loads(raw)
    contract_file = contract_path or Path(__file__).with_name("runtime-contract.json")
    contract_file = Path(contract_file)
    adapter_requirements = Path(__file__).with_name("requirements-e2b.txt")
    contract = json.loads(contract_file.read_text())
    python_parts = tuple(int(part) for part in str(observed["python"]).split(".")[:2])
    if contract.get("python") != ">=3.12,<3.13" or python_parts != (3, 12):
        raise ValueError(
            f"unsupported OSWorld Python {observed['python']}; expected {contract.get('python')}"
        )
    for distribution in ("anthropic", "e2b"):
        if observed.get(distribution) != contract.get(distribution):
            raise ValueError(
                f"unsupported {distribution} {observed.get(distribution)}; "
                f"expected {contract.get(distribution)}"
            )
    return {
        "schema_version": 1,
        "python_executable": str(python_executable),
        "python": observed["python"],
        "anthropic": observed["anthropic"],
        "adapter_requirements_sha256": _sha256(adapter_requirements),
        "e2b": observed["e2b"],
        "osworld_commit": actual_commit,
        "osworld_lock_sha256": _sha256(lock_path),
        "runner": runner_relative,
        "runner_sha256": _sha256(runner_path),
        "runtime_contract_sha256": _sha256(contract_file),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--python", dest="python_executable", type=Path, required=True)
    inspect_parser.add_argument("--osworld-root", type=Path, required=True)
    inspect_parser.add_argument("--runner", type=Path, required=True)
    inspect_parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args()
    try:
        identity = inspect_runtime(
            python_executable=args.python_executable,
            osworld_root=args.osworld_root,
            runner=args.runner,
            expected_commit=args.expected_commit,
        )
    except (
        json.JSONDecodeError,
        OSError,
        subprocess.CalledProcessError,
        ValueError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(identity, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
