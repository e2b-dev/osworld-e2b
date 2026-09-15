#!/usr/bin/env python3
"""Generate or verify a committed inventory from a clean OSWorld checkout."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from runner.profile import build_inventory, select_profile, write_inventory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", type=Path, default=Path("validation/profiles.json"))
    parser.add_argument("--profile", required=True)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        profile = select_profile(args.profile, args.profiles)
        actual = subprocess.check_output(
            ["git", "-C", str(args.checkout), "rev-parse", "HEAD"], text=True
        ).strip()
        if actual != profile["commit"]:
            raise ValueError(
                f"OSWorld commit mismatch for {args.profile}: expected {profile['commit']}, got {actual}"
            )
        if subprocess.check_output(
            ["git", "-C", str(args.checkout), "status", "--porcelain"], text=True
        ).strip():
            raise ValueError(f"OSWorld checkout is not clean: {args.checkout}")
        write_inventory(
            args.output,
            build_inventory(args.checkout, profile, args.suite),
            check=args.check,
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
