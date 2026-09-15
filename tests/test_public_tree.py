from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        ".env.production",
        ".venv/bin/python",
        "node_modules/pkg/index.js",
        "results/run.json",
        "repro/probe.ts",
        "runner/OSWorld/.git/config",
        "artifacts/template.json",
        "cache/download.bin",
        "out/raw/trajectory.json",
        "run/agent.log",
        "template/files/server/__pycache__/main.pyc",
    ],
)
def test_generated_or_sensitive_paths_are_ignored(path: str) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", path],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0, f"expected {path!r} to be ignored"


@pytest.mark.parametrize("path", [".env.example", "realkit/relay.py", "validation/manifest.json"])
def test_public_source_paths_remain_trackable(path: str) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", path],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 1, f"expected {path!r} to remain trackable"


def test_current_public_tree_passes_release_gate() -> None:
    result = subprocess.run(
        [os.environ.get("PYTHON", "python3"), str(ROOT / "scripts" / "check_public_tree.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_public_tree_gate_rejects_forbidden_tracked_file(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    forbidden = tmp_path / ".env.local"
    forbidden.write_text("E2B_API_KEY=not-a-real-key\n")
    subprocess.run(["git", "add", "--force", ".env.local"], cwd=tmp_path, check=True)

    result = subprocess.run(
        [
            os.environ.get("PYTHON", "python3"),
            str(ROOT / "scripts" / "check_public_tree.py"),
            "--root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert ".env.local" in result.stdout
