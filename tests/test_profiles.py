from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner.profile import build_inventory, load_inventory, load_profiles, select_profile

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "validation" / "profiles.json"
INVENTORIES = ROOT / "validation" / "inventories"


def _task(checkout: Path, domain: str, task_id: str, *, proxy: bool = False) -> None:
    path = checkout / "evaluation_examples" / "examples" / domain / f"{task_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"id": task_id, "instruction": task_id, "proxy": proxy}) + "\n")


def _checkout(tmp_path: Path) -> Path:
    checkout = tmp_path / "OSWorld"
    _task(checkout, "chrome", "task-a", proxy=True)
    _task(checkout, "gimp", "task-b")
    _task(checkout, "chrome", "task-gdrive")
    examples = checkout / "evaluation_examples"
    (examples / "test_all.json").write_text(
        json.dumps({"chrome": ["task-a", "task-gdrive"], "gimp": ["task-b"]}) + "\n"
    )
    (examples / "test_nogdrive.json").write_text(
        json.dumps({"chrome": ["task-a"], "gimp": ["task-b"]}) + "\n"
    )
    evaluator = checkout / "desktop_env" / "evaluators" / "metrics.py"
    evaluator.parent.mkdir(parents=True)
    evaluator.write_text("def score(): return 1\n")
    return checkout


def test_current_profile_covers_the_complete_official_suites() -> None:
    profile = select_profile("current-v1", PROFILES)

    assert profile["commit"] == "fc31a9049664292fcb35d6e501ee1dc839f2cf6d"
    assert load_inventory(INVENTORIES / "current-v1-all.json")["task_count"] == 369
    assert load_inventory(INVENTORIES / "current-v1-nogdrive.json")["task_count"] == 361
    assert load_inventory(INVENTORIES / "current-v1-gdrive.json")["task_count"] == 8


def test_parity_profile_pins_the_historical_upstream_and_public_evidence() -> None:
    profile = select_profile("ui-mopd-qwen3vl-docker", PROFILES)

    assert profile["commit"] == "fe8c78e15a1149e82d54137e9ffef18aee710ed7"
    assert profile["source_commit_provenance"] == "inferred_from_run_date"
    assert profile["reference"]["dataset_commit"] == ("a518b8776c172c9456f85b3fa5ef451d326a7969")
    assert load_inventory(INVENTORIES / "ui-mopd-qwen3vl-docker-nogdrive.json")["task_count"] == 361


def test_profile_loader_rejects_mutable_and_malformed_commits(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps(
            {
                "default_profile": "bad",
                "profiles": {
                    "bad": {
                        "repository": "https://github.com/xlang-ai/OSWorld.git",
                        "commit": "main",
                        "suites": {},
                    }
                },
            }
        )
    )

    with pytest.raises(ValueError, match="40 lowercase hexadecimal"):
        load_profiles(path)


def test_build_inventory_hashes_tasks_proxy_flags_and_evaluators(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path)
    profile = {
        "name": "fixture",
        "repository": "https://github.com/xlang-ai/OSWorld.git",
        "commit": "1" * 40,
        "suites": {
            "all": {"upstream_manifest": "evaluation_examples/test_all.json"},
            "nogdrive": {"upstream_manifest": "evaluation_examples/test_nogdrive.json"},
            "gdrive": {
                "upstream_manifest": "evaluation_examples/test_all.json",
                "difference_from": "nogdrive",
            },
        },
    }

    inventory = build_inventory(checkout, profile, "all")

    assert inventory["task_count"] == 3
    assert [item["id"] for item in inventory["tasks"]] == [
        "task-a",
        "task-gdrive",
        "task-b",
    ]
    assert inventory["tasks"][0]["proxy"] is True
    assert len(inventory["tasks"][0]["task_sha256"]) == 64
    assert len(inventory["evaluator_tree_sha256"]) == 64
    assert len(inventory["inventory_sha256"]) == 64


def test_gdrive_inventory_is_the_ordered_all_minus_nogdrive_difference(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path)
    profile = {
        "name": "fixture",
        "repository": "https://github.com/xlang-ai/OSWorld.git",
        "commit": "1" * 40,
        "suites": {
            "all": {"upstream_manifest": "evaluation_examples/test_all.json"},
            "nogdrive": {"upstream_manifest": "evaluation_examples/test_nogdrive.json"},
            "gdrive": {
                "upstream_manifest": "evaluation_examples/test_all.json",
                "difference_from": "nogdrive",
            },
        },
    }

    inventory = build_inventory(checkout, profile, "gdrive")

    assert [(item["domain"], item["id"]) for item in inventory["tasks"]] == [
        ("chrome", "task-gdrive")
    ]


def test_unknown_profile_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown OSWorld profile"):
        select_profile("osworld-main", PROFILES)
