#!/usr/bin/env python3
"""Validate third-party action references in a GitHub Actions workflow."""

from __future__ import annotations

import re
from pathlib import Path

ACTION = re.compile(r"^\s*-\s+uses:\s*['\"]?([^'\"#\s]+)")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
JOB = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
STEP = re.compile(r"^      - ")
GITLEAKS_VERSION = re.compile(r"^\s*GITLEAKS_VERSION:\s*[0-9]+\.[0-9]+\.[0-9]+\s*$", re.MULTILINE)
GITLEAKS_CHECKSUM = re.compile(r"^\s*GITLEAKS_SHA256:\s*[0-9a-f]{64}\s*$", re.MULTILINE)
OFFICIAL_ARCHIVE = (
    "https://github.com/gitleaks/gitleaks/releases/download/"
    "v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"
)
CHECKSUM_COMMAND = 'echo "${GITLEAKS_SHA256}  ${archive}" | sha256sum --check --strict'
HISTORY_COMMAND = '"$RUNNER_TEMP/gitleaks" git --redact --verbose .'


def _job(lines: list[str], name: str) -> list[str]:
    start = next(
        (index for index, line in enumerate(lines) if line == f"  {name}:"),
        None,
    )
    if start is None:
        return []
    end = next(
        (index for index in range(start + 1, len(lines)) if JOB.match(lines[index])),
        len(lines),
    )
    return lines[start:end]


def _steps(job: list[str]) -> list[list[str]]:
    starts = [index for index, line in enumerate(job) if STEP.match(line)]
    return [
        job[start : starts[position + 1] if position + 1 < len(starts) else len(job)]
        for position, start in enumerate(starts)
    ]


def workflow_action_violations(path: Path) -> list[str]:
    text = path.read_text()
    lines = text.splitlines()
    violations: list[str] = []
    for line_number, line in enumerate(lines, start=1):
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

    secrets_steps = _steps(_job(lines, "secrets"))
    checkout = next(
        (step for step in secrets_steps if any("uses: actions/checkout@" in line for line in step)),
        [],
    )
    if not any(re.fullmatch(r"\s*fetch-depth:\s*0", line) for line in checkout):
        violations.append("secrets checkout must use fetch-depth: 0 for a full-history scan")

    scan = next(
        (step for step in secrets_steps if any("GITLEAKS_VERSION:" in line for line in step)),
        [],
    )
    scan_text = "\n".join(scan)
    if GITLEAKS_VERSION.search(scan_text) is None:
        violations.append("Gitleaks CLI must use a fixed numeric version")
    if OFFICIAL_ARCHIVE not in scan_text:
        violations.append("Gitleaks CLI must use the official versioned GitHub release URL")
    if GITLEAKS_CHECKSUM.search(scan_text) is None or CHECKSUM_COMMAND not in scan_text:
        violations.append("Gitleaks install must verify the pinned SHA-256")
    if HISTORY_COMMAND not in scan_text:
        violations.append("secrets job must run the direct Gitleaks CLI history scan")
    return violations
