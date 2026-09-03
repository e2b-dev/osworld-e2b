"""Immutable OSWorld profiles and deterministic task inventories."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_profiles(path: Path) -> dict:
    document = json.loads(Path(path).read_text())
    profiles = document.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("profiles.json must contain a non-empty profiles object")
    if document.get("default_profile") not in profiles:
        raise ValueError("default_profile must name a declared profile")
    for name, profile in profiles.items():
        commit = profile.get("commit", "")
        if not COMMIT_RE.fullmatch(commit):
            raise ValueError(f"profile {name} commit must be 40 lowercase hexadecimal characters")
        if profile.get("repository") != "https://github.com/xlang-ai/OSWorld.git":
            raise ValueError(f"profile {name} has an unexpected OSWorld repository")
        if not isinstance(profile.get("suites"), dict) or not profile["suites"]:
            raise ValueError(f"profile {name} must declare suites")
    return document


def select_profile(name: str, path: Path) -> dict:
    profiles = load_profiles(path)["profiles"]
    if name not in profiles:
        raise ValueError(f"unknown OSWorld profile: {name}")
    return {"name": name, **profiles[name]}


def _read_suite(checkout: Path, profile: dict, suite: str) -> list[tuple[str, str]]:
    suites = profile["suites"]
    if suite not in suites:
        raise ValueError(f"profile {profile['name']} does not declare suite {suite}")
    suite_config = suites[suite]
    manifest_path = checkout / suite_config["upstream_manifest"]
    manifest = json.loads(manifest_path.read_text())
    selected = [(domain, task_id) for domain, task_ids in manifest.items() for task_id in task_ids]
    difference_from = suite_config.get("difference_from")
    if difference_from:
        excluded = set(_read_suite(checkout, profile, difference_from))
        selected = [task for task in selected if task not in excluded]
    return selected


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        relative = path.relative_to(root).as_posix().encode()
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def build_inventory(checkout: Path, profile: dict, suite: str) -> dict:
    checkout = Path(checkout)
    tasks = []
    for domain, task_id in _read_suite(checkout, profile, suite):
        task_path = checkout / "evaluation_examples" / "examples" / domain / f"{task_id}.json"
        raw = task_path.read_bytes()
        task = json.loads(raw)
        tasks.append(
            {
                "domain": domain,
                "id": task_id,
                "task_sha256": _sha256(raw),
                "proxy": bool(task.get("proxy", False)),
            }
        )
    inventory = {
        "schema_version": 1,
        "profile": profile["name"],
        "repository": profile["repository"],
        "commit": profile["commit"],
        "suite": suite,
        "task_count": len(tasks),
        "evaluator_tree_sha256": _tree_digest(checkout / "desktop_env" / "evaluators"),
        "tasks": tasks,
    }
    inventory["inventory_sha256"] = _sha256(_canonical_bytes(inventory))
    return inventory


def load_inventory(path: Path) -> dict:
    inventory = json.loads(Path(path).read_text())
    expected = inventory.get("inventory_sha256")
    unsigned = {key: value for key, value in inventory.items() if key != "inventory_sha256"}
    actual = _sha256(_canonical_bytes(unsigned))
    if expected != actual:
        raise ValueError(f"inventory checksum mismatch: expected {expected}, computed {actual}")
    if inventory.get("task_count") != len(inventory.get("tasks", [])):
        raise ValueError("inventory task_count does not match tasks")
    return inventory


def write_inventory(path: Path, inventory: dict, *, check: bool = False) -> None:
    rendered = json.dumps(inventory, indent=2, sort_keys=True) + "\n"
    path = Path(path)
    if check:
        if not path.exists() or path.read_text() != rendered:
            raise ValueError(f"inventory is out of date: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered)


def verify_profile_checkout(checkout: Path, profile: dict, repo_root: Path) -> None:
    actual_commit = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual_commit != profile["commit"]:
        raise ValueError(
            f"OSWorld commit mismatch for {profile['name']}: "
            f"expected {profile['commit']}, got {actual_commit}"
        )
    for suite, suite_config in profile["suites"].items():
        expected = load_inventory(repo_root / suite_config["inventory"])
        actual = build_inventory(checkout, profile, suite)
        if expected != actual:
            raise ValueError(
                f"inventory drift for profile {profile['name']} suite {suite}: "
                f"expected {expected['inventory_sha256']}, got {actual['inventory_sha256']}"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("--name", required=True)
    get_parser.add_argument("--field", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--name", required=True)
    verify_parser.add_argument("--checkout", type=Path, required=True)
    verify_parser.add_argument("--repo-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        profile = select_profile(args.name, args.profiles)
        if args.command == "get":
            value = profile.get(args.field)
            if not isinstance(value, str):
                raise ValueError(f"profile field is not a string: {args.field}")
            print(value)
        else:
            verify_profile_checkout(args.checkout, profile, args.repo_root)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
