from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "runner" / "patch_upstream.py"


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=False, capture_output=True, text=True)


def _checkout(tmp_path: Path) -> tuple[Path, str]:
    checkout = tmp_path / "OSWorld"
    checkout.mkdir()
    _run("git", "init", "-q", "-b", "main", cwd=checkout)
    _run("git", "config", "user.email", "test@example.com", cwd=checkout)
    _run("git", "config", "user.name", "Test", cwd=checkout)
    providers = checkout / "desktop_env" / "providers"
    providers.mkdir(parents=True)
    (providers / "__init__.py").write_text(
        "def create(provider_name, region):\n    else:\n        raise NotImplementedError\n"
    )
    (checkout / "desktop_env" / "desktop_env.py").write_text(
        'CLOUD_PROVIDERS = {"fastvm", "pyromind", "modal"}\n'
        "def reset(self):\n"
        "    if self.is_environment_used:\n"
        "        return self.provider.revert_to_snapshot()\n"
    )
    _run("git", "add", ".", cwd=checkout)
    _run("git", "commit", "-qm", "fixture", cwd=checkout)
    head = _run("git", "rev-parse", "HEAD", cwd=checkout).stdout.strip()
    return checkout, head


def test_upstream_patcher_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    checkout, head = _checkout(tmp_path)

    first = _run("python3", str(PATCHER), str(checkout), "--expected-commit", head)
    assert first.returncode == 0, first.stdout + first.stderr
    first_diff = _run("git", "diff", "--binary", "HEAD", cwd=checkout).stdout

    second = _run("python3", str(PATCHER), str(checkout), "--expected-commit", head)
    assert second.returncode == 0, second.stdout + second.stderr
    second_diff = _run("git", "diff", "--binary", "HEAD", cwd=checkout).stdout

    assert first_diff == second_diff
    assert 'provider_name == "e2b"' in (checkout / "desktop_env/providers/__init__.py").read_text()
    assert 'self.provider_name == "e2b"' in (checkout / "desktop_env/desktop_env.py").read_text()


def test_upstream_patcher_rejects_the_wrong_commit(tmp_path: Path) -> None:
    checkout, _ = _checkout(tmp_path)

    result = _run("python3", str(PATCHER), str(checkout), "--expected-commit", "0" * 40)

    assert result.returncode == 1
    assert "commit mismatch" in result.stderr


def test_upstream_patcher_rejects_unowned_tracked_changes(tmp_path: Path) -> None:
    checkout, head = _checkout(tmp_path)
    unexpected = checkout / "desktop_env" / "unrelated.py"
    unexpected.write_text("value = 1\n")
    _run("git", "add", "desktop_env/unrelated.py", cwd=checkout)
    _run("git", "commit", "-qm", "add unrelated", cwd=checkout)
    head = _run("git", "rev-parse", "HEAD", cwd=checkout).stdout.strip()
    unexpected.write_text("value = 2\n")

    result = _run("python3", str(PATCHER), str(checkout), "--expected-commit", head)

    assert result.returncode == 1
    assert "unexpected checkout changes" in result.stderr
