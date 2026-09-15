from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner.minimax_sample import build_comparison, build_runtime_provenance, build_sample_inventory

ROOT = Path(__file__).resolve().parents[1]


def test_reference_sample_matches_pinned_current_inventory() -> None:
    inventory = json.loads((ROOT / "validation/inventories/current-v1-nogdrive.json").read_text())
    reference = json.loads(
        (ROOT / "validation/reference/minimax-m3-osworld-verified-sample.json").read_text()
    )

    sample = build_sample_inventory(inventory, reference)

    assert sample["task_count"] == 10
    assert len({item["domain"] for item in sample["tasks"]}) == 10
    assert all(item["proxy"] is False for item in sample["tasks"])


def test_sample_inventory_rejects_task_content_drift() -> None:
    inventory = {
        "profile": "current-v1",
        "suite": "nogdrive",
        "inventory_sha256": "f" * 64,
        "tasks": [{"domain": "chrome", "id": "task-a", "task_sha256": "a" * 64, "proxy": False}],
    }
    reference = {
        "sample": {
            "tasks": [
                {
                    "domain": "chrome",
                    "id": "task-a",
                    "task_sha256": "b" * 64,
                    "published_reward": 1.0,
                }
            ]
        }
    }

    with pytest.raises(ValueError, match="task content drift"):
        build_sample_inventory(inventory, reference)


def test_comparison_reports_task_agreement_and_score_delta() -> None:
    reference = {
        "public_run": {"score": 0.75},
        "sample": {
            "score": 0.5,
            "tasks": [
                {"domain": "chrome", "id": "task-a", "published_reward": 1.0},
                {"domain": "vlc", "id": "task-b", "published_reward": 0.0},
            ],
        },
    }

    comparison = build_comparison({("chrome", "task-a"): 1.0, ("vlc", "task-b"): 1.0}, reference)

    assert comparison["ready"] is True
    assert comparison["e2b_sample_score"] == 1.0
    assert comparison["published_sample_score"] == 0.5
    assert comparison["absolute_sample_score_delta"] == 0.5
    assert comparison["task_reward_agreements"] == 1
    assert comparison["tasks"][1]["agrees"] is False


def test_runtime_provenance_captures_dependency_identity() -> None:
    assert build_runtime_provenance("3.13.1", "0.84.0") == {
        "python": "3.13.1",
        "anthropic": "0.84.0",
        "transport": "anthropic_messages",
    }


def test_retained_diagnostic_receipt_is_internally_consistent() -> None:
    receipt = json.loads((ROOT / "validation/evidence/minimax-m3-e2b-diverse-10.json").read_text())
    reference = json.loads(
        (ROOT / "validation/reference/minimax-m3-osworld-verified-sample.json").read_text()
    )

    assert receipt["classification"] == "diagnostic_sample_not_release_parity"
    assert receipt["source"]["osworld_commit"] == reference["reproduction"]["osworld_commit"]
    assert receipt["public_reference"]["selected_task_count"] == reference["sample"]["task_count"]
    assert receipt["public_reference"]["selected_score"] == reference["sample"]["score"]
    assert receipt["e2b"]["valid_tasks"] == receipt["e2b"]["task_count"]
    assert receipt["e2b"]["sandbox_creates"] == receipt["e2b"]["sandbox_cleans"]
    assert receipt["e2b"]["sandbox_cleanup_failures"] == 0
    assert receipt["e2b"]["model_call_errors"] == 0
    assert receipt["e2b"]["artifact_checksum_errors"] == 0
    assert receipt["e2b"]["fireworks_api_key_byte_hits"] == 0
