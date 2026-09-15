from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_setup_default_checkout_stays_in_ignored_runner_directory(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    git = fake_bin / "git"
    git.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$GIT_ARGS_LOG"\nexit 77\n')
    git.chmod(0o755)
    log = tmp_path / "git-args"
    environment = {
        **os.environ,
        "GIT_ARGS_LOG": str(log),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
    }

    result = subprocess.run(
        [str(ROOT / "runner/setup.sh")],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 77
    assert log.read_text().splitlines()[-1] == str(ROOT / "runner/OSWorld")


def test_setup_rejects_an_unknown_profile_before_git(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    git = fake_bin / "git"
    git.write_text("#!/bin/sh\necho git-should-not-run >&2\nexit 99\n")
    git.chmod(0o755)

    result = subprocess.run(
        [str(ROOT / "runner/setup.sh"), "--profile", "osworld-main"],
        cwd=ROOT,
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "unknown OSWorld profile" in result.stderr
    assert "git-should-not-run" not in result.stderr
