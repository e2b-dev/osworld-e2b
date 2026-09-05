from __future__ import annotations

import importlib.util
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
    assert '"e2b"' in generic
    assert "OSWORLD_LOG_DIR" in generic
    assert 'parser.add_argument("--api_backend", choices=["openai", "dashscope"]' in qwen
    assert "api_backend=args.api_backend" in qwen
    assert 'parser.add_argument("--vm_secret_mount"' in qwen
    assert "vm_secret_mounts=args.vm_secret_mount" in qwen


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
