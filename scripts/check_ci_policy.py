#!/usr/bin/env python3
"""Validate third-party action references in a GitHub Actions workflow."""

from __future__ import annotations

import re
from pathlib import Path

ACTION = re.compile(r"^\s*-\s+uses:\s*['\"]?([^'\"#\s]+)")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
GITLEAKS_HISTORY_SCAN = re.compile(r"gitleaks['\"]?\s+git\s+--redact")
GITLEAKS_CHECKSUM = re.compile(r"^\s*GITLEAKS_SHA256:\s*[0-9a-f]{64}\s*$", re.MULTILINE)
FULL_HISTORY = re.compile(r"^\s*fetch-depth:\s*0\s*$", re.MULTILINE)


def workflow_action_violations(path: Path) -> list[str]:
    text = path.read_text()
    violations: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = ACTION.match(line)
        if match is None:
            continue
        action = match.group(1)
        if action.startswith("./"):
            continue
        owner_repository, separator, reference = action.rpartition("@")
        if owner_repository == "gitleaks/gitleaks-action":
            violations.append(
                f"line {line_number}: license-gated gitleaks action is forbidden; "
                "install the CLI directly"
            )
        elif not separator or COMMIT.fullmatch(reference) is None:
            violations.append(
                f"line {line_number}: external action must use a full 40-character commit SHA: "
                f"{action}"
            )
    if not (
        GITLEAKS_HISTORY_SCAN.search(text)
        and GITLEAKS_CHECKSUM.search(text)
        and FULL_HISTORY.search(text)
    ):
        violations.append("workflow must checksum-pin a direct Gitleaks CLI history scan")
    return violations
