#!/usr/bin/env python3
"""Apply the OSWorld E2B adapter patch to a pinned, controlled checkout."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

OWNED_TRACKED_PATHS = {
    "desktop_env/desktop_env.py",
    "desktop_env/providers/__init__.py",
}
OWNED_UNTRACKED_PREFIXES = ("desktop_env/providers/e2b/",)
OWNED_UNTRACKED_FILES = {
    "e2b_harness.py",
    "e2b_policy.py",
    "e2b_relay.py",
}


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def _provider_factory(source: str) -> str:
    branch = (
        '    elif provider_name == "e2b":\n'
        "        from desktop_env.providers.e2b.manager import E2BVMManager\n"
        "        from desktop_env.providers.e2b.provider import E2BProvider\n"
        "        return E2BVMManager(), E2BProvider(region)\n"
    )
    anchor = "    else:\n        raise NotImplementedError"
    if branch in source:
        return source
    if anchor not in source:
        raise RuntimeError("providers/__init__.py anchor not found; OSWorld contract moved")
    return source.replace(anchor, branch + anchor)


def _desktop_env(source: str) -> str:
    cloud_anchor = '"fastvm", "pyromind", "modal"}'
    if '"fastvm", "pyromind", "modal", "e2b"}' not in source:
        if cloud_anchor not in source:
            raise RuntimeError(
                "desktop_env.py cloud-provider anchor not found; OSWorld contract moved"
            )
        source = source.replace(cloud_anchor, '"fastvm", "pyromind", "modal", "e2b"}')

    strict_reset = 'if self.is_environment_used or self.provider_name == "e2b":\n'
    if strict_reset not in source:
        reset_anchor = "if self.is_environment_used:\n"
        if reset_anchor not in source:
            raise RuntimeError("desktop_env.py reset anchor not found; OSWorld contract moved")
        source = source.replace(reset_anchor, strict_reset, 1)
    return source


TRANSFORMS = {
    "desktop_env/providers/__init__.py": _provider_factory,
    "desktop_env/desktop_env.py": _desktop_env,
}


def _is_owned_untracked(path: str) -> bool:
    return path in OWNED_UNTRACKED_FILES or path.startswith(OWNED_UNTRACKED_PREFIXES)


def patch_checkout(root: Path, expected_commit: str) -> None:
    root = root.resolve()
    if not (root / ".git").exists():
        raise RuntimeError(f"not a Git checkout: {root}")
    actual_commit = git(root, "rev-parse", "HEAD")
    if actual_commit != expected_commit:
        raise RuntimeError(
            f"OSWorld commit mismatch: expected {expected_commit}, got {actual_commit}"
        )

    changed = set(filter(None, git(root, "diff", "--name-only", "HEAD").splitlines()))
    untracked = set(
        filter(None, git(root, "ls-files", "--others", "--exclude-standard").splitlines())
    )
    unexpected = sorted(
        (changed - OWNED_TRACKED_PATHS)
        | {path for path in untracked if not _is_owned_untracked(path)}
    )
    if unexpected:
        raise RuntimeError(f"unexpected checkout changes: {', '.join(unexpected)}")

    outputs: dict[str, str] = {}
    for relative, transform in TRANSFORMS.items():
        pristine = git(root, "show", f"HEAD:{relative}") + "\n"
        expected = transform(pristine)
        current = (root / relative).read_text()
        if current not in {pristine, expected}:
            raise RuntimeError(f"owned checkout file diverged from the generated patch: {relative}")
        outputs[relative] = expected

    for relative, expected in outputs.items():
        (root / relative).write_text(expected)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("checkout", type=Path)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args()
    try:
        patch_checkout(args.checkout, args.expected_commit)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OSWorld adapter patch verified at {args.expected_commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
