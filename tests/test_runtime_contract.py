from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _runtime_fixture(
    tmp_path: Path, *, anthropic: str = "0.84.0"
) -> tuple[Path, str, Path, Path, str, str]:
    environment = tmp_path / ".venv"
    subprocess.run(["uv", "venv", "--python", "3.12", str(environment)], check=True)
    interpreter = environment / "bin" / "python"
    python_version = subprocess.check_output(
        [interpreter, "-c", "import platform; print(platform.python_version())"], text=True
    ).strip()
    fake_site = Path(
        subprocess.check_output(
            [interpreter, "-c", "import site; print(site.getsitepackages()[0])"], text=True
        ).strip()
    )
    for distribution, version in (("anthropic", anthropic), ("e2b", "2.33.0")):
        metadata = fake_site / f"{distribution}-{version}.dist-info" / "METADATA"
        metadata.parent.mkdir(parents=True)
        metadata.write_text(f"Metadata-Version: 2.1\nName: {distribution}\nVersion: {version}\n")
    checkout = tmp_path / "OSWorld"
    checkout.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=checkout, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=checkout, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=checkout, check=True)
    lock = checkout / "uv.lock"
    lock.write_text("version = 1\n")
    runner = checkout / "runner.py"
    runner.write_text("print('runner')\n")
    subprocess.run(["git", "add", "."], cwd=checkout, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=checkout, check=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True).strip()
    return interpreter, python_version, checkout, runner, commit, anthropic


def test_runtime_contract_pins_the_supported_osworld_environment() -> None:
    contract = json.loads((ROOT / "runner/runtime-contract.json").read_text())

    assert contract == {
        "schema_version": 1,
        "python": ">=3.12,<3.13",
        "anthropic": "0.84.0",
        "e2b": "2.33.0",
    }


def test_adapter_runtime_requirements_pin_the_complete_overlay() -> None:
    requirements = {
        line
        for line in (ROOT / "runner/requirements-e2b.txt").read_text().splitlines()
        if line and not line.startswith("#")
    }

    assert requirements == {
        "aiohttp==3.14.3",
        "bracex==3.0.1",
        "dockerfile-parse==2.0.1",
        "e2b==2.33.0",
        "h2==4.4.1",
        "hpack==4.2.0",
        "hyperframe==6.1.0",
        "wcmatch==10.2.1",
    }


def test_runtime_inspector_records_the_executable_dependencies_and_source(
    tmp_path: Path,
) -> None:
    interpreter, python_version, checkout, runner, commit, anthropic = _runtime_fixture(tmp_path)

    result = subprocess.run(
        [
            "python3",
            str(ROOT / "runner/runtime.py"),
            "inspect",
            "--python",
            str(interpreter),
            "--osworld-root",
            str(checkout),
            "--runner",
            "runner.py",
            "--expected-commit",
            commit,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "schema_version": 1,
        "python_executable": str(interpreter.absolute()),
        "python": python_version,
        "anthropic": anthropic,
        "adapter_requirements_sha256": hashlib.sha256(
            (ROOT / "runner/requirements-e2b.txt").read_bytes()
        ).hexdigest(),
        "e2b": "2.33.0",
        "osworld_commit": commit,
        "osworld_lock_sha256": hashlib.sha256((checkout / "uv.lock").read_bytes()).hexdigest(),
        "runner": "runner.py",
        "runner_sha256": hashlib.sha256(runner.read_bytes()).hexdigest(),
        "runtime_contract_sha256": hashlib.sha256(
            (ROOT / "runner/runtime-contract.json").read_bytes()
        ).hexdigest(),
    }


def test_runtime_inspector_rejects_dependency_drift_before_execution(tmp_path: Path) -> None:
    interpreter, _, checkout, runner, commit, _ = _runtime_fixture(tmp_path, anthropic="1.4.0")

    result = subprocess.run(
        [
            "python3",
            str(ROOT / "runner/runtime.py"),
            "inspect",
            "--python",
            str(interpreter),
            "--osworld-root",
            str(checkout),
            "--runner",
            runner.name,
            "--expected-commit",
            commit,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "unsupported anthropic 1.4.0; expected 0.84.0" in result.stderr


def test_runtime_inspector_rejects_upstream_lock_drift(tmp_path: Path) -> None:
    interpreter, _, checkout, runner, commit, _ = _runtime_fixture(tmp_path)
    (checkout / "uv.lock").write_text("modified = true\n")

    result = subprocess.run(
        [
            "python3",
            str(ROOT / "runner/runtime.py"),
            "inspect",
            "--python",
            str(interpreter),
            "--osworld-root",
            str(checkout),
            "--runner",
            runner.name,
            "--expected-commit",
            commit,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "OSWorld lock differs from the pinned commit" in result.stderr
