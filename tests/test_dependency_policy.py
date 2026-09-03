from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _requirements(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_-]+)==([0-9][A-Za-z0-9_.-]*)", line)
        assert match is not None, f"dependency must use an exact pin: {line}"
        pins[match.group(1).lower()] = match.group(2)
    return pins


def _version(value: str) -> tuple[int, ...]:
    match = re.fullmatch(r"(\d+(?:\.\d+)*)", value)
    assert match is not None, f"expected a stable numeric version, got {value!r}"
    return tuple(int(part) for part in match.group(1).split("."))


def _project_dependencies() -> dict[str, str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    pins = _requirements_from_strings(project["project"]["dependencies"])
    for group in project["dependency-groups"].values():
        pins.update(_requirements_from_strings(group))
    return pins


def _requirements_from_strings(requirements: list[str]) -> dict[str, str]:
    pins: dict[str, str] = {}
    for requirement in requirements:
        match = re.fullmatch(r"([A-Za-z0-9_-]+)==([0-9][A-Za-z0-9_.-]*)", requirement)
        assert match is not None, f"dependency must use an exact pin: {requirement}"
        pins[match.group(1).lower()] = match.group(2)
    return pins


def test_host_and_runner_use_the_same_fixed_aiohttp_release() -> None:
    host = _project_dependencies()
    runner = _requirements(ROOT / "runner/requirements-e2b.txt")

    assert host["aiohttp"] == runner["aiohttp"]
    assert _version(host["aiohttp"]) >= (3, 14, 3)


def test_guest_security_sensitive_pins_are_at_or_above_fixed_releases() -> None:
    guest = _requirements(ROOT / "template/files/server/requirements.txt")
    minimums = {
        "aiohttp": (3, 14, 3),
        "flask": (3, 1, 3),
        "lxml": (6, 1, 0),
        "pillow": (12, 3, 0),
        "requests": (2, 33, 0),
    }

    for dependency, minimum in minimums.items():
        assert _version(guest[dependency]) >= minimum


def test_test_runner_uses_a_non_vulnerable_release() -> None:
    assert _version(_project_dependencies()["pytest"]) >= (9, 0, 3)
