"""Crash-visible result accounting for OSWorld task attempts."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

INVALID_REASONS = {
    "runner_exit",
    "timeout",
    "missing_result",
    "malformed_result",
    "identity_drift",
    "cleanup_failed",
    "interrupted",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


@dataclass(frozen=True, order=True)
class TaskKey:
    domain: str
    id: str

    def to_dict(self) -> dict[str, str]:
        return {"domain": self.domain, "id": self.id}


@dataclass(frozen=True)
class AttemptEvent:
    event: str
    task: TaskKey
    attempt: int
    timestamp: str
    attempt_dir: str | None = None
    pid: int | None = None
    outcome: str | None = None
    reason: str | None = None
    reward: float | None = None
    cleanup: str | None = None
    artifacts: tuple[dict, ...] = ()

    def __post_init__(self) -> None:
        if self.attempt < 1:
            raise ValueError("attempt must be positive")
        if self.event not in {"PLANNED", "STARTED", "TERMINAL"}:
            raise ValueError(f"unknown attempt event: {self.event}")
        if self.event == "TERMINAL":
            if self.outcome == "valid":
                if self.reward is None or not math.isfinite(self.reward):
                    raise ValueError("valid result requires a finite reward")
                if self.cleanup != "success":
                    raise ValueError("valid result requires successful cleanup")
                if self.reason is not None:
                    raise ValueError("valid result cannot have an invalid reason")
            elif self.outcome == "invalid":
                if self.reason not in INVALID_REASONS:
                    raise ValueError(f"unknown invalid reason: {self.reason}")
                if self.reward is not None:
                    raise ValueError("invalid result cannot carry a reward")
            else:
                raise ValueError("terminal event requires valid or invalid outcome")

    @classmethod
    def planned(cls, task: TaskKey, attempt: int, attempt_dir: str) -> AttemptEvent:
        return cls("PLANNED", task, attempt, _utc_now(), attempt_dir=attempt_dir)

    @classmethod
    def started(cls, task: TaskKey, attempt: int, pid: int) -> AttemptEvent:
        return cls("STARTED", task, attempt, _utc_now(), pid=pid)

    @classmethod
    def valid(
        cls,
        task: TaskKey,
        attempt: int,
        *,
        reward: float,
        cleanup: str,
        artifacts: list[dict] | tuple[dict, ...] = (),
    ) -> AttemptEvent:
        return cls(
            "TERMINAL",
            task,
            attempt,
            _utc_now(),
            outcome="valid",
            reward=reward,
            cleanup=cleanup,
            artifacts=tuple(artifacts),
        )

    @classmethod
    def invalid(
        cls,
        task: TaskKey,
        attempt: int,
        reason: str,
        *,
        cleanup: str | None,
        artifacts: list[dict] | tuple[dict, ...] = (),
    ) -> AttemptEvent:
        return cls(
            "TERMINAL",
            task,
            attempt,
            _utc_now(),
            outcome="invalid",
            reason=reason,
            cleanup=cleanup,
            artifacts=tuple(artifacts),
        )

    def to_dict(self) -> dict:
        record = {
            "event": self.event,
            "domain": self.task.domain,
            "task_id": self.task.id,
            "attempt": self.attempt,
            "timestamp": self.timestamp,
        }
        for key in (
            "attempt_dir",
            "pid",
            "outcome",
            "reason",
            "reward",
            "cleanup",
        ):
            value = getattr(self, key)
            if value is not None:
                record[key] = value
        if self.artifacts:
            record["artifacts"] = list(self.artifacts)
        return record


class RunLedger:
    def __init__(self, root: Path, document: dict):
        self.root = Path(root)
        self.document = document
        self.fingerprint = document["campaign_fingerprint"]
        self.tasks = tuple(TaskKey(item["domain"], item["id"]) for item in document["tasks"])
        self._task_set = set(self.tasks)

    @classmethod
    def create(cls, root: Path, *, metadata: dict, tasks: list[TaskKey]) -> RunLedger:
        root = Path(root)
        if root.exists() and any(root.iterdir()):
            raise ValueError(f"run directory is not empty: {root}")
        root.mkdir(parents=True, exist_ok=True)
        task_records = [task.to_dict() for task in tasks]
        if len(set(tasks)) != len(tasks):
            raise ValueError("run task inventory contains duplicates")
        fingerprint = hashlib.sha256(
            _canonical_bytes({"metadata": metadata, "tasks": task_records})
        ).hexdigest()
        document = {
            "schema_version": 1,
            "created_at": _utc_now(),
            "campaign_fingerprint": fingerprint,
            "metadata": metadata,
            "tasks": task_records,
        }
        _atomic_json(root / "run.json", document)
        (root / "attempts.jsonl").touch()
        ledger = cls(root, document)
        ledger._write_aggregate(ledger.aggregate())
        return ledger

    @classmethod
    def open(cls, root: Path, *, expected_fingerprint: str | None = None) -> RunLedger:
        root = Path(root)
        document = json.loads((root / "run.json").read_text())
        ledger = cls(root, document)
        if expected_fingerprint is not None and ledger.fingerprint != expected_fingerprint:
            raise ValueError(
                "campaign fingerprint mismatch: "
                f"expected {expected_fingerprint}, got {ledger.fingerprint}"
            )
        return ledger

    def _events(self) -> list[dict]:
        path = self.root / "attempts.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def append(self, event: AttemptEvent) -> None:
        if event.task not in self._task_set:
            raise ValueError(f"task is outside the run inventory: {event.task}")
        task_events = [
            item
            for item in self._events()
            if item["domain"] == event.task.domain
            and item["task_id"] == event.task.id
            and item["attempt"] == event.attempt
        ]
        if event.event == "PLANNED":
            if task_events:
                raise ValueError("attempt is already planned")
            if event.task in self.terminal_tasks():
                raise ValueError("task already has a valid terminal event")
        elif event.event == "STARTED":
            if not task_events or task_events[-1]["event"] != "PLANNED":
                raise ValueError("STARTED must follow PLANNED")
        elif not task_events or task_events[-1]["event"] != "STARTED":
            if any(item["event"] == "TERMINAL" for item in task_events):
                raise ValueError("attempt already has a terminal event")
            raise ValueError("TERMINAL must follow STARTED")

        path = self.root / "attempts.jsonl"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self._write_aggregate(self.aggregate())

    def terminal_tasks(self) -> set[TaskKey]:
        return {
            TaskKey(item["domain"], item["task_id"])
            for item in self._events()
            if item["event"] == "TERMINAL" and item.get("outcome") == "valid"
        }

    def resume_candidates(self, max_attempts: int) -> list[tuple[TaskKey, int]]:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        events = self._events()
        valid = self.terminal_tasks()
        candidates = []
        for task in self.tasks:
            if task in valid:
                continue
            matching = [
                item
                for item in events
                if item["domain"] == task.domain and item["task_id"] == task.id
            ]
            if not matching:
                candidates.append((task, 1))
                continue
            latest_attempt = max(item["attempt"] for item in matching)
            latest = [item for item in matching if item["attempt"] == latest_attempt]
            if latest[-1]["event"] == "PLANNED":
                candidates.append((task, latest_attempt))
            elif latest_attempt < max_attempts:
                candidates.append((task, latest_attempt + 1))
        return candidates

    def aggregate(self) -> dict:
        events = self._events()
        attempts: dict[tuple[str, str, int], list[dict]] = {}
        for event in events:
            key = (event["domain"], event["task_id"], event["attempt"])
            attempts.setdefault(key, []).append(event)
        terminals = [event for event in events if event["event"] == "TERMINAL"]
        valid_by_task = {}
        invalid_by_reason: dict[str, int] = {}
        for event in terminals:
            if event.get("outcome") == "valid":
                valid_by_task[(event["domain"], event["task_id"])] = event["reward"]
            else:
                reason = event["reason"]
                invalid_by_reason[reason] = invalid_by_reason.get(reason, 0) + 1
        missing = sum(
            any(item["event"] == "STARTED" for item in history)
            and not any(item["event"] == "TERMINAL" for item in history)
            for history in attempts.values()
        )
        rewards = list(valid_by_task.values())
        return {
            "schema_version": 1,
            "campaign_fingerprint": self.fingerprint,
            "planned_tasks": len(self.tasks),
            "planned_attempts": sum(event["event"] == "PLANNED" for event in events),
            "started_attempts": sum(event["event"] == "STARTED" for event in events),
            "terminal_attempts": len(terminals),
            "missing_attempts": missing,
            "valid_tasks": len(valid_by_task),
            "remaining_tasks": len(self.tasks) - len(valid_by_task),
            "invalid_by_reason": dict(sorted(invalid_by_reason.items())),
            "reward_sum": sum(rewards),
            "score": (sum(rewards) / len(rewards)) if rewards else None,
        }

    def _write_aggregate(self, aggregate: dict) -> None:
        _atomic_json(self.root / "aggregate.json", aggregate)

    def refresh_aggregate(self, **extra: object) -> dict:
        aggregate = {**self.aggregate(), **extra}
        self._write_aggregate(aggregate)
        return aggregate


def catalog_artifacts(root: Path) -> list[dict]:
    root = Path(root)
    artifacts = []
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        raw = path.read_bytes()
        artifacts.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return artifacts
