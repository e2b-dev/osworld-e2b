from __future__ import annotations

import json
from pathlib import Path

import pytest

from realkit.preflight import (
    collect_environment_redaction_values,
    collect_redaction_values,
    redact_text,
    sanitize_mount,
    validate_capabilities,
)

PROXY_TASK = {"domain": "chrome", "id": "proxy-task", "proxy": True}
PLAIN_TASK = {"domain": "gimp", "id": "plain-task", "proxy": False}


def test_proxy_tasks_reject_upstream_placeholder_credentials(tmp_path: Path) -> None:
    proxy = tmp_path / "proxy.json"
    proxy.write_text(
        '[{"host":"gw.dataimpulse.com","port":823,'
        '"username":"your_username","password":"your_password"}]'
    )

    with pytest.raises(ValueError, match="placeholder proxy credentials"):
        validate_capabilities([PROXY_TASK], "nogdrive", proxy, [])


def test_proxy_tasks_require_a_readable_configuration() -> None:
    with pytest.raises(ValueError, match="PROXY_CONFIG_FILE"):
        validate_capabilities([PROXY_TASK], "nogdrive", None, [])


def test_plain_tasks_do_not_require_proxy_configuration() -> None:
    evidence = validate_capabilities([PLAIN_TASK], "nogdrive", None, [])

    assert evidence.proxy == {"required_task_count": 0, "configured": False}


def test_secret_evidence_never_contains_host_path_or_bytes(tmp_path: Path) -> None:
    secret = tmp_path / "google.json"
    secret.write_text('{"private_key":"secret-private-key"}')

    evidence = sanitize_mount(f"{secret}:/opt/osworld/secrets/google.json")
    rendered = json.dumps(evidence)

    assert str(secret) not in rendered
    assert "secret-private-key" not in rendered
    assert evidence["guest_path"] == "/opt/osworld/secrets/google.json"
    assert evidence["source_label"] == "google.json"
    assert len(evidence["source_sha256"]) == 64


@pytest.mark.parametrize("suite", ["all", "gdrive"])
def test_authenticated_suites_require_secret_mounts(suite: str) -> None:
    with pytest.raises(ValueError, match="secret mount"):
        validate_capabilities([PLAIN_TASK], suite, None, [])


def test_secret_mounts_are_restricted_to_the_guest_secret_directory(tmp_path: Path) -> None:
    secret = tmp_path / "google.json"
    secret.write_text("{}")

    with pytest.raises(ValueError, match="/opt/osworld/secrets"):
        sanitize_mount(f"{secret}:/home/user/google.json")


def test_proxy_evidence_contains_only_hash_label_and_task_count(tmp_path: Path) -> None:
    proxy = tmp_path / "proxy.json"
    proxy.write_text(
        '[{"host":"proxy.example","port":8080,"username":"account","password":"s3cret"}]'
    )

    evidence = validate_capabilities([PROXY_TASK], "nogdrive", proxy, [])
    rendered = json.dumps(evidence.to_dict())

    assert str(proxy) not in rendered
    assert "account" not in rendered
    assert "s3cret" not in rendered
    assert evidence.proxy["source_label"] == "proxy.json"


def test_redaction_covers_paths_json_secret_values_urls_and_api_keys(tmp_path: Path) -> None:
    secret = tmp_path / "google.json"
    secret.write_text('{"private_key":"private-value","client_email":"bot@example.test"}')
    proxy = tmp_path / "proxy.json"
    proxy.write_text(
        '[{"host":"proxy.example","port":8080,"username":"account","password":"s3cret"}]'
    )
    values = collect_redaction_values(proxy, [f"{secret}:/opt/osworld/secrets/google.json"])
    raw = (
        f"mount {secret}; private-value; bot@example.test; "
        "http://account:s3cret@proxy.example:8080; e2b_1234567890abcdefghijklmnop"
    )

    redacted = redact_text(raw, values)

    assert str(secret) not in redacted
    assert "private-value" not in redacted
    assert "bot@example.test" not in redacted
    assert "account:s3cret" not in redacted
    assert "e2b_1234567890abcdefghijklmnop" not in redacted
    assert "<redacted>" in redacted


def test_environment_redaction_collects_secret_values_and_explicit_endpoints() -> None:
    values = collect_environment_redaction_values(
        {
            "OPENAI_API_KEY": "provider-secret-value",
            "MODEL_ACCESS_TOKEN": "endpoint-token-value",
            "PATH": "/usr/bin",
        },
        ["https://user:token@model.example/v1"],
    )

    assert "provider-secret-value" in values
    assert "endpoint-token-value" in values
    assert "https://user:token@model.example/v1" in values
    assert "/usr/bin" not in values
