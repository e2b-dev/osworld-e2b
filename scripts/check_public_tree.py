#!/usr/bin/env python3
"""Reject generated, secret-prone, or vendored paths from a proposed public tree."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path, PurePosixPath

FORBIDDEN_PARTS = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "artifacts",
    "cache",
    "dist",
    "node_modules",
    "out",
    "repro",
    "results",
    "trajectories",
    "venv",
}
FORBIDDEN_SUFFIXES = {".log", ".pid", ".pyc", ".pyo", ".token"}


def tracked_and_candidate_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [path.decode() for path in result.stdout.split(b"\0") if path]


def forbidden_reason(path: str) -> str | None:
    candidate = PurePosixPath(path)
    parts = set(candidate.parts)
    name = candidate.name
    if name == ".DS_Store":
        return "macOS metadata"
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return "dotenv file"
    if "runner" in parts and "OSWorld" in parts:
        return "vendored OSWorld checkout"
    if parts & FORBIDDEN_PARTS:
        return "generated, cached, or vendored directory"
    if candidate.suffix in FORBIDDEN_SUFFIXES:
        return "runtime or generated file"
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    violations = [
        (path, reason)
        for path in tracked_and_candidate_paths(root)
        if (reason := forbidden_reason(path)) is not None
    ]
    if violations:
        for path, reason in sorted(violations):
            print(f"FORBIDDEN {path}: {reason}")
        return 1
    print("Public tree contains no forbidden paths.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
