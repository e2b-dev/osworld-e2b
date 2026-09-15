#!/usr/bin/env python3
"""Live probe: OSWorld save_state/revert_to_snapshot mapped to E2B snapshots.

Requires a running relay (realkit/relay.py). Verifies that a snapshot saved
mid-run captures the exact guest state (marker file present after revert) and
that a plain reset returns to the template base state (marker absent).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

CONTROL = "http://127.0.0.1:14999"
GUEST = "http://127.0.0.1:15000"
MARKER = "/home/user/snapshot-probe-marker"
ROOT = Path(__file__).resolve().parent.parent


def call(url, payload=None, timeout=600):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"} if data else {}
    with urlopen(
        Request(url, data=data, method="POST" if data is not None else "GET", headers=headers),
        timeout=timeout,
    ) as r:
        return json.load(r)


def execute(command):
    return call(f"{GUEST}/execute", {"command": command, "shell": True})


def marker_exists():
    result = execute(f"test -f {MARKER} && echo present || echo absent")
    return result["output"].strip() == "present"


def main() -> int:
    report = {"tested_at": datetime.now(timezone.utc).isoformat(), "checks": {}}

    state = call(f"{CONTROL}/health")
    report["template"] = state["template"]
    report["sandbox_a"] = state["sandbox_id"]
    report["checks"]["initial guest from template"] = state["source"] == "template"

    execute(f"echo mid-task-state > {MARKER}")
    report["checks"]["marker written in sandbox A"] = marker_exists()

    saved = call(f"{CONTROL}/save", {"name": "probe_state"})
    report["snapshot_id"] = saved["snapshot_id"]
    report["checks"]["snapshot saved"] = bool(saved["snapshot_id"])
    report["checks"]["sandbox A resumed after snapshot"] = marker_exists()

    reverted = call(f"{CONTROL}/reset", {"snapshot": "probe_state"})
    report["sandbox_b"] = reverted["sandbox_id"]
    report["checks"]["revert created a new sandbox"] = reverted["sandbox_id"] != state["sandbox_id"]
    report["checks"]["revert source is the snapshot"] = (
        reverted["source"] == f"snapshot:{saved['snapshot_id']}"
    )
    report["checks"]["restricted ingress preserved"] = reverted["restricted_ingress"] is True
    report["checks"]["marker survives snapshot revert"] = marker_exists()

    base = call(f"{CONTROL}/reset", {"snapshot": "init_state"})
    report["sandbox_c"] = base["sandbox_id"]
    report["checks"]["unsaved name falls back to template"] = base["source"] == "template"
    report["checks"]["marker absent after template reset"] = not marker_exists()

    report["all_checks_passed"] = all(report["checks"].values())
    out = ROOT / "results" / "snapshot-probe.json"
    out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    print(json.dumps(report, indent=1, sort_keys=True))
    return 0 if report["all_checks_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
