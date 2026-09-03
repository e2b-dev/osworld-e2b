from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from realkit.results import AttemptEvent, RunLedger, TaskKey, catalog_artifacts

TASK_A = TaskKey("chrome", "task-a")
TASK_B = TaskKey("gimp", "task-b")


def _ledger(tmp_path: Path) -> RunLedger:
    return RunLedger.create(
        tmp_path / "run",
        metadata={"profile": "fixture", "template": "fixture:00000000-0000-0000-0000-000000000001"},
        tasks=[TASK_A, TASK_B],
    )


def _append_started(ledger: RunLedger, task: TaskKey, attempt: int = 1) -> None:
    ledger.append(
        AttemptEvent.planned(task, attempt, f"attempts/{task.domain}/{task.id}/{attempt}")
    )
    ledger.append(AttemptEvent.started(task, attempt, pid=1234))


def test_valid_zero_is_scored_while_missing_is_invalid(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    _append_started(ledger, TASK_A)
    ledger.append(AttemptEvent.valid(TASK_A, 1, reward=0.0, cleanup="success"))
    _append_started(ledger, TASK_B)
    ledger.append(AttemptEvent.invalid(TASK_B, 1, "missing_result", cleanup="success"))

    aggregate = ledger.aggregate()

    assert aggregate["valid_tasks"] == 1
    assert aggregate["terminal_attempts"] == 2
    assert aggregate["invalid_by_reason"] == {"missing_result": 1}
    assert aggregate["score"] == 0.0
    assert aggregate["reward_sum"] == 0.0


def test_unmatched_started_event_is_visible_as_missing_and_resumable(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    _append_started(ledger, TASK_A)

    aggregate = ledger.aggregate()

    assert aggregate["missing_attempts"] == 1
    assert aggregate["terminal_attempts"] == 0
    assert ledger.resume_candidates(max_attempts=2) == [(TASK_A, 2), (TASK_B, 1)]


def test_invalid_attempt_retries_but_valid_task_does_not(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    _append_started(ledger, TASK_A)
    ledger.append(AttemptEvent.invalid(TASK_A, 1, "timeout", cleanup="success"))
    _append_started(ledger, TASK_B)
    ledger.append(AttemptEvent.valid(TASK_B, 1, reward=0.5, cleanup="success"))

    assert ledger.resume_candidates(max_attempts=2) == [(TASK_A, 2)]
    assert ledger.resume_candidates(max_attempts=1) == []
    assert ledger.terminal_tasks() == {TASK_B}


def test_duplicate_terminal_and_nonfinite_reward_are_rejected(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    _append_started(ledger, TASK_A)
    ledger.append(AttemptEvent.valid(TASK_A, 1, reward=1.0, cleanup="success"))

    with pytest.raises(ValueError, match="already has a terminal event"):
        ledger.append(AttemptEvent.invalid(TASK_A, 1, "runner_exit", cleanup="success"))
    with pytest.raises(ValueError, match="finite reward"):
        AttemptEvent.valid(TASK_B, 1, reward=float("nan"), cleanup="success")


def test_cleanup_failure_cannot_be_a_valid_result(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="successful cleanup"):
        AttemptEvent.valid(TASK_A, 1, reward=1.0, cleanup="failed")


def test_campaign_fingerprint_detects_metadata_drift(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)

    reopened = RunLedger.open(ledger.root, expected_fingerprint=ledger.fingerprint)
    assert reopened.fingerprint == ledger.fingerprint
    with pytest.raises(ValueError, match="campaign fingerprint mismatch"):
        RunLedger.open(ledger.root, expected_fingerprint="0" * 64)


def test_artifact_catalog_records_relative_paths_sizes_and_hashes(tmp_path: Path) -> None:
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    (attempt / "result.txt").write_text("0.5\n")
    (attempt / "traj.jsonl").write_text('{"step":1}\n')

    catalog = catalog_artifacts(attempt)

    by_path = {item["path"]: item for item in catalog}
    assert set(by_path) == {"result.txt", "traj.jsonl"}
    assert by_path["result.txt"]["bytes"] == 4
    assert by_path["result.txt"]["sha256"] == hashlib.sha256(b"0.5\n").hexdigest()


def test_aggregate_json_is_regenerated_after_each_event(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.append(AttemptEvent.planned(TASK_A, 1, "attempts/chrome/task-a/1"))

    on_disk = json.loads((ledger.root / "aggregate.json").read_text())

    assert on_disk["planned_attempts"] == 1
    assert on_disk["missing_attempts"] == 0
