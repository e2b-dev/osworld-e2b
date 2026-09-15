from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "runner" / "patch_upstream.py"


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=False, capture_output=True, text=True)


def _checkout(
    tmp_path: Path,
    cloud_providers: str = '{"fastvm", "pyromind", "modal"}',
) -> tuple[Path, str]:
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
        f"if self.provider_name in {cloud_providers}:\n"
        "    self.is_environment_used = False\n"
        "def reset(self):\n"
        "    if self.is_environment_used:\n"
        "        return self.provider.revert_to_snapshot()\n"
    )
    scripts = checkout / "scripts" / "python"
    scripts.mkdir(parents=True)
    (scripts / "run_multienv.py").write_text(
        'LOG = os.path.join("logs", "normal.log")\n'
        'parser.add_argument("--provider_name", choices=["docker", "daytona"])\n'
    )
    (scripts / "run_multienv_qwen3vl.py").write_text(
        'LOG = os.path.join("logs", "normal.log")\n'
        '    parser.add_argument("--path_to_vm", type=str, default=None)\n'
        'parser.add_argument("--provider_name", choices=["docker", "daytona"])\n'
        "    # example config\n"
        "env = DesktopEnv(\n"
        "            client_password=args.client_password,\n"
        ")\n"
        "agent = Qwen3VLAgent(\n"
        "            model=args.model,\n"
        ")\n\n\n"
    )
    (scripts / "run_multienv_m3.py").write_text(
        'LOG = os.path.join("logs", "normal.log")\n'
        'os.makedirs("logs", exist_ok=True)\n'
        '    parser.add_argument("--path_to_vm", type=str, default=None)\n'
        'parser.add_argument("--provider_name", choices=["docker", "daytona"])\n'
        "        env_kwargs = dict(\n"
        "            client_password=client_password,\n"
        "            enable_proxy=args.enable_proxy,\n"
        "        )\n"
        "        env = DesktopEnv(**env_kwargs)\n"
    )
    agents = checkout / "mm_agents"
    agents.mkdir()
    (agents / "qwen3vl_agent.py").write_text(
        "class Qwen3VLAgent:\n    def reset(self, _logger=None):\n        self.logger = _logger\n"
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
    generic = (checkout / "scripts/python/run_multienv.py").read_text()
    qwen = (checkout / "scripts/python/run_multienv_qwen3vl.py").read_text()
    m3 = (checkout / "scripts/python/run_multienv_m3.py").read_text()
    assert '"e2b"' in generic
    assert "OSWORLD_LOG_DIR" in generic
    assert 'parser.add_argument("--api_backend", choices=["openai", "dashscope"]' in qwen
    assert "api_backend=args.api_backend" in qwen
    assert 'parser.add_argument("--vm_secret_mount"' in qwen
    assert "vm_secret_mounts=args.vm_secret_mount" in qwen
    assert '"e2b"' in m3
    assert "OSWORLD_LOG_DIR" in m3
    assert 'os.makedirs(os.environ.get("OSWORLD_LOG_DIR", "logs"), exist_ok=True)' in m3
    assert 'parser.add_argument("--vm_secret_mount"' in m3
    assert "vm_secret_mounts=args.vm_secret_mount" in m3


@pytest.mark.parametrize(
    "providers",
    [
        '{"fastvm", "pyromind", "modal"}',
        '{"docker", "aws", "gcp", "azure", "aliyun", "volcengine", "fastvm"}',
        '{"docker", "aws", "fastvm", "pyromind", "modal", "daytona"}',
    ],
)
def test_desktop_patch_supports_historical_and_current_provider_sets(
    tmp_path: Path, providers: str
) -> None:
    checkout, head = _checkout(tmp_path, providers)

    result = _run("python3", str(PATCHER), str(checkout), "--expected-commit", head)

    assert result.returncode == 0, result.stdout + result.stderr
    source = (checkout / "desktop_env/desktop_env.py").read_text()
    assert '"e2b"' in source
    assert 'self.provider_name == "e2b"' in source


def test_upstream_patcher_rejects_the_wrong_commit(tmp_path: Path) -> None:
    checkout, _ = _checkout(tmp_path)

    result = _run("python3", str(PATCHER), str(checkout), "--expected-commit", "0" * 40)

    assert result.returncode == 1
    assert "commit mismatch" in result.stderr


def test_patched_qwen_agent_reset_accepts_vm_ip_without_changing_logger(tmp_path: Path) -> None:
    checkout, head = _checkout(tmp_path)

    result = _run("python3", str(PATCHER), str(checkout), "--expected-commit", head)

    assert result.returncode == 0, result.stdout + result.stderr
    agent_path = checkout / "mm_agents" / "qwen3vl_agent.py"
    spec = importlib.util.spec_from_file_location("fixture_qwen3vl_agent", agent_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    logger = object()
    agent = module.Qwen3VLAgent()
    agent.reset(logger, vm_ip="127.0.0.1")
    assert agent.logger is logger


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


def test_restore_owned_patch_returns_checkout_to_pristine_head(tmp_path: Path) -> None:
    from runner.patch_upstream import restore_owned_patch

    checkout, head = _checkout(tmp_path)
    result = _run("python3", str(PATCHER), str(checkout), "--expected-commit", head)
    assert result.returncode == 0, result.stdout + result.stderr
    source = ROOT / "realkit"
    destination = checkout / "desktop_env" / "providers" / "e2b"
    destination.mkdir()
    shutil.copy(source / "provider.py", destination / "provider.py")
    (checkout / "e2b_relay.py").write_text("generated\n")

    restore_owned_patch(checkout)

    assert _run("git", "diff", "--exit-code", "HEAD", cwd=checkout).returncode == 0
    assert not destination.exists()
    assert not (checkout / "e2b_relay.py").exists()


def test_owned_restore_allows_bidirectional_git_profile_switches(tmp_path: Path) -> None:
    from runner.patch_upstream import patch_checkout, restore_owned_patch

    checkout, first_commit = _checkout(tmp_path)
    desktop_env = checkout / "desktop_env" / "desktop_env.py"
    desktop_env.write_text(desktop_env.read_text().replace('"modal"', '"daytona"'))
    (checkout / "profile-marker.txt").write_text("second\n")
    _run("git", "add", "desktop_env/desktop_env.py", "profile-marker.txt", cwd=checkout)
    _run("git", "commit", "-qm", "second profile", cwd=checkout)
    second_commit = _run("git", "rev-parse", "HEAD", cwd=checkout).stdout.strip()
    _run("git", "checkout", "--detach", "--quiet", first_commit, cwd=checkout)
    patch_checkout(checkout, first_commit)
    destination = checkout / "desktop_env" / "providers" / "e2b"
    destination.mkdir()
    shutil.copy(ROOT / "realkit" / "provider.py", destination / "provider.py")

    blocked = _run("git", "checkout", "--detach", "--quiet", second_commit, cwd=checkout)
    assert blocked.returncode != 0

    restore_owned_patch(checkout)
    assert (
        _run("git", "checkout", "--detach", "--quiet", second_commit, cwd=checkout).returncode == 0
    )
    patch_checkout(checkout, second_commit)
    restore_owned_patch(checkout)
    assert (
        _run("git", "checkout", "--detach", "--quiet", first_commit, cwd=checkout).returncode == 0
    )


def test_patch_verifier_rejects_adapter_owned_source_drift(tmp_path: Path) -> None:
    from runner.patch_upstream import patch_checkout, verify_patched_checkout

    checkout, head = _checkout(tmp_path)
    patch_checkout(checkout, head)
    runner = checkout / "scripts" / "python" / "run_multienv_m3.py"
    runner.write_text(runner.read_text() + "# local mutation\n")

    with pytest.raises(RuntimeError, match="generated adapter drift"):
        verify_patched_checkout(checkout, head)
