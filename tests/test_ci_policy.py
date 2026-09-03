from __future__ import annotations

from pathlib import Path

from scripts.check_ci_policy import workflow_action_violations

ROOT = Path(__file__).resolve().parents[1]


def test_policy_rejects_mutable_and_license_gated_action_references(tmp_path: Path) -> None:
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        """steps:
  - uses: actions/checkout@v4
    with:
      fetch-depth: 0
  - uses: gitleaks/gitleaks-action@0123456789abcdef0123456789abcdef01234567
  - run: '"$RUNNER_TEMP/gitleaks" git --redact --verbose .'
env:
  GITLEAKS_SHA256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
"""
    )

    violations = workflow_action_violations(workflow)

    assert violations == [
        "line 2: external action must use a full 40-character commit SHA: actions/checkout@v4",
        "line 5: license-gated gitleaks action is forbidden; install the CLI directly",
    ]


def test_policy_requires_a_checksum_pinned_direct_history_scan(tmp_path: Path) -> None:
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        """steps:
  - uses: actions/checkout@0123456789abcdef0123456789abcdef01234567
"""
    )

    assert workflow_action_violations(workflow) == [
        "workflow must checksum-pin a direct Gitleaks CLI history scan"
    ]


def test_repository_workflow_uses_immutable_license_free_actions() -> None:
    assert workflow_action_violations(ROOT / ".github/workflows/ci.yml") == []
