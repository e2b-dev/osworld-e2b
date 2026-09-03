from __future__ import annotations

from pathlib import Path

from scripts.check_ci_policy import workflow_action_violations

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/ci.yml").read_text()


def _check_mutation(tmp_path: Path, text: str) -> list[str]:
    workflow = tmp_path / "ci.yml"
    workflow.write_text(text)
    return workflow_action_violations(workflow)


def _mutate_secrets_job(old: str, new: str) -> str:
    prefix, separator, secrets = WORKFLOW.partition("  secrets:\n")
    assert separator
    assert old in secrets
    return f"{prefix}{separator}{secrets.replace(old, new, 1)}"


def test_policy_rejects_mutable_and_license_gated_action_references(tmp_path: Path) -> None:
    mutable = WORKFLOW.replace(
        "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
        "actions/checkout@v4",
        1,
    )
    gated = mutable.replace(
        "      - name: Scan complete Git history with Gitleaks",
        "      - uses: gitleaks/gitleaks-action@0123456789abcdef0123456789abcdef01234567\n"
        "      - name: Scan complete Git history with Gitleaks",
    )

    violations = _check_mutation(tmp_path, gated)

    assert any("actions/checkout@v4" in violation for violation in violations)
    assert any("license-gated gitleaks action" in violation for violation in violations)


def test_policy_rejects_missing_checksum_verification(tmp_path: Path) -> None:
    mutated = _mutate_secrets_job(
        '          echo "${GITLEAKS_SHA256}  ${archive}" | sha256sum --check --strict\n',
        '          echo "checksum verification removed"\n',
    )

    violations = _check_mutation(tmp_path, mutated)

    assert any("verify the pinned SHA-256" in violation for violation in violations)


def test_policy_rejects_shallow_secrets_checkout(tmp_path: Path) -> None:
    mutated = _mutate_secrets_job("          fetch-depth: 0\n", "          fetch-depth: 1\n")

    violations = _check_mutation(tmp_path, mutated)

    assert any("fetch-depth: 0" in violation for violation in violations)


def test_policy_rejects_unpinned_gitleaks_version(tmp_path: Path) -> None:
    mutated = _mutate_secrets_job(
        "          GITLEAKS_VERSION: 8.30.1\n",
        "          GITLEAKS_VERSION: latest\n",
    )

    violations = _check_mutation(tmp_path, mutated)

    assert any("fixed numeric version" in violation for violation in violations)


def test_policy_rejects_nonofficial_gitleaks_download(tmp_path: Path) -> None:
    mutated = _mutate_secrets_job(
        "https://github.com/gitleaks/gitleaks/releases/",
        "https://example.invalid/",
    )

    violations = _check_mutation(tmp_path, mutated)

    assert any("official versioned GitHub release URL" in violation for violation in violations)


def test_repository_workflow_uses_immutable_license_free_actions() -> None:
    assert workflow_action_violations(ROOT / ".github/workflows/ci.yml") == []
