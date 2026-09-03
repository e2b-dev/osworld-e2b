"""Capability validation and secret-safe evidence for OSWorld campaigns."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

PLACEHOLDERS = {
    "",
    "changeme",
    "password",
    "your_password",
    "your_username",
    "username",
}
GUEST_SECRET_ROOT = PurePosixPath("/opt/osworld/secrets")


@dataclass(frozen=True)
class CapabilityEvidence:
    proxy: dict
    secret_mounts: tuple[dict, ...]

    def to_dict(self) -> dict:
        return {"proxy": self.proxy, "secret_mounts": list(self.secret_mounts)}


def _split_mount(mount: str) -> tuple[Path, str]:
    if ":" not in mount:
        raise ValueError("secret mount must use local_path:guest_path syntax")
    local_path, guest_path = mount.rsplit(":", 1)
    if not local_path or not guest_path:
        raise ValueError("secret mount must use local_path:guest_path syntax")
    return Path(local_path).expanduser().resolve(), guest_path


def sanitize_mount(mount: str) -> dict[str, str]:
    local_path, guest_path = _split_mount(mount)
    if not local_path.is_file():
        raise ValueError(f"secret mount source is not a readable file: {local_path.name}")
    guest = PurePosixPath(guest_path)
    if not guest.is_absolute() or (
        guest != GUEST_SECRET_ROOT and GUEST_SECRET_ROOT not in guest.parents
    ):
        raise ValueError("secret mount guest path must be inside /opt/osworld/secrets")
    return {
        "guest_path": str(guest),
        "source_label": local_path.name,
        "source_sha256": hashlib.sha256(local_path.read_bytes()).hexdigest(),
    }


def _load_proxy(path: Path) -> list[dict]:
    try:
        document = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("PROXY_CONFIG_FILE must be readable valid JSON") from error
    if (
        not isinstance(document, list)
        or not document
        or not all(isinstance(item, dict) for item in document)
    ):
        raise ValueError("PROXY_CONFIG_FILE must contain a non-empty proxy list")
    for proxy in document:
        username = str(proxy.get("username", "")).strip().lower()
        password = str(proxy.get("password", "")).strip().lower()
        host = str(proxy.get("host", "")).strip()
        port = proxy.get("port")
        if username in PLACEHOLDERS or password in PLACEHOLDERS:
            raise ValueError("PROXY_CONFIG_FILE contains placeholder proxy credentials")
        if not host or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("PROXY_CONFIG_FILE contains an invalid proxy endpoint")
    return document


def validate_capabilities(
    tasks: list[dict],
    suite: str,
    proxy_config: Path | None,
    secret_mounts: list[str] | tuple[str, ...],
) -> CapabilityEvidence:
    proxy_task_count = sum(bool(task.get("proxy")) for task in tasks)
    if proxy_task_count:
        if proxy_config is None:
            raise ValueError("proxy-required tasks need PROXY_CONFIG_FILE")
        proxy_config = Path(proxy_config).expanduser().resolve()
        _load_proxy(proxy_config)
        proxy = {
            "required_task_count": proxy_task_count,
            "configured": True,
            "source_label": proxy_config.name,
            "source_sha256": hashlib.sha256(proxy_config.read_bytes()).hexdigest(),
        }
    else:
        proxy = {"required_task_count": 0, "configured": False}
    if suite in {"all", "gdrive"} and not secret_mounts:
        raise ValueError(f"suite {suite} requires at least one Google credential secret mount")
    mounts = tuple(sanitize_mount(mount) for mount in secret_mounts)
    return CapabilityEvidence(proxy=proxy, secret_mounts=mounts)


def _json_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if len(value) >= 4 else []
    if isinstance(value, list):
        return [item for child in value for item in _json_strings(child)]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _json_strings(child)]
    return []


def collect_redaction_values(
    proxy_config: Path | None, secret_mounts: list[str] | tuple[str, ...]
) -> tuple[str, ...]:
    values = set()
    paths = []
    if proxy_config is not None:
        paths.append(Path(proxy_config).expanduser().resolve())
    for mount in secret_mounts:
        local_path, _ = _split_mount(mount)
        paths.append(local_path)
    for path in paths:
        values.add(str(path))
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if len(text) >= 4:
            values.add(text)
        try:
            values.update(_json_strings(json.loads(text)))
        except json.JSONDecodeError:
            pass
    return tuple(sorted(values, key=len, reverse=True))


def redact_text(text: str, sensitive_values: tuple[str, ...] | list[str]) -> str:
    for value in sensitive_values:
        if value:
            text = text.replace(value, "<redacted>")
    text = re.sub(r"(https?://)[^\s/@:]+:[^\s/@]+@", r"\1<redacted>:<redacted>@", text)
    text = re.sub(r"\be2b_[A-Za-z0-9_-]{20,}\b", "<redacted>", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{16,}\b", "<redacted>", text)
    return text
