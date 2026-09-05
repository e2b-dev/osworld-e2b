#!/usr/bin/env python3
"""Apply the OSWorld E2B adapter patch to a pinned, controlled checkout."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

OWNED_TRACKED_PATHS = {
    "desktop_env/desktop_env.py",
    "desktop_env/providers/__init__.py",
    "mm_agents/qwen3vl_agent.py",
    "scripts/python/run_multienv.py",
    "scripts/python/run_multienv_qwen3vl.py",
}
OWNED_UNTRACKED_PREFIXES = ("desktop_env/providers/e2b/",)
OWNED_UNTRACKED_FILES = {
    "e2b_harness.py",
    "e2b_policy.py",
    "e2b_relay.py",
}


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def git_show(root: Path, relative: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), "show", f"HEAD:{relative}"], text=True)


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
    cloud_set = re.compile(
        r"(?P<prefix>if self\.provider_name\s+in\s+\{)"
        r'(?P<body>[^{}\n]*"fastvm"[^{}\n]*)'
        r"(?P<suffix>\})"
    )
    match = cloud_set.search(source)
    if match is None:
        raise RuntimeError("desktop_env.py cloud-provider set not found; OSWorld contract moved")
    if '"e2b"' not in match.group("body"):
        body = match.group("body").rstrip()
        source = source[: match.start("body")] + body + ', "e2b"' + source[match.end("body") :]

    strict_reset = 'if self.is_environment_used or self.provider_name == "e2b":\n'
    if strict_reset not in source:
        reset_anchor = "if self.is_environment_used:\n"
        if reset_anchor not in source:
            raise RuntimeError("desktop_env.py reset anchor not found; OSWorld contract moved")
        source = source.replace(reset_anchor, strict_reset, 1)
    return source


def _runner(source: str) -> str:
    provider_block = re.compile(
        r"(?P<prefix>--provider_name[\s\S]{0,400}?choices\s*=\s*\[)(?P<body>[^\]]*)(?P<suffix>\])"
    )
    match = provider_block.search(source)
    if match is None:
        raise RuntimeError("runner provider choices not found; OSWorld contract moved")
    if '"e2b"' not in match.group("body"):
        body = match.group("body").rstrip()
        comma = "" if body.endswith(",") else ","
        source = (
            source[: match.start("body")] + body + comma + ' "e2b"' + source[match.end("body") :]
        )
    return source.replace(
        'os.path.join("logs",',
        'os.path.join(os.environ.get("OSWORLD_LOG_DIR", "logs"),',
    )


def _qwen_runner(source: str) -> str:
    source = _runner(source)
    mount_argument = '    parser.add_argument("--vm_secret_mount", action="append", default=None)\n'
    if mount_argument not in source:
        anchor = '    parser.add_argument("--path_to_vm", type=str, default=None)\n'
        if anchor not in source:
            raise RuntimeError("Qwen runner VM-path anchor not found; OSWorld contract moved")
        source = source.replace(anchor, anchor + mount_argument, 1)
    mount_forwarding = "            vm_secret_mounts=args.vm_secret_mount,\n"
    if mount_forwarding not in source:
        anchor = "            client_password=args.client_password,\n"
        if anchor not in source:
            raise RuntimeError(
                "Qwen runner DesktopEnv constructor anchor not found; OSWorld contract moved"
            )
        source = source.replace(anchor, anchor + mount_forwarding, 1)
    api_argument = (
        '    parser.add_argument("--api_backend", choices=["openai", "dashscope"], '
        'default="openai")\n'
    )
    if api_argument not in source:
        anchor = "    # example config\n"
        if anchor not in source:
            raise RuntimeError(
                "Qwen runner example-config anchor not found; OSWorld contract moved"
            )
        source = source.replace(anchor, api_argument + "\n" + anchor, 1)
    backend_argument = "            api_backend=args.api_backend,\n"
    if backend_argument not in source:
        anchor = "            model=args.model,\n"
        if anchor not in source:
            raise RuntimeError("Qwen agent constructor anchor not found; OSWorld contract moved")
        source = source.replace(anchor, anchor + backend_argument, 1)
    return source


def _qwen_agent(source: str) -> str:
    compatible = "    def reset(self, _logger=None, vm_ip=None):\n"
    if compatible in source:
        return source
    anchor = "    def reset(self, _logger=None):\n"
    if anchor not in source:
        raise RuntimeError("Qwen agent reset anchor not found; OSWorld contract moved")
    return source.replace(anchor, compatible, 1)


TRANSFORMS = {
    "desktop_env/providers/__init__.py": _provider_factory,
    "desktop_env/desktop_env.py": _desktop_env,
    "mm_agents/qwen3vl_agent.py": _qwen_agent,
    "scripts/python/run_multienv.py": _runner,
    "scripts/python/run_multienv_qwen3vl.py": _qwen_runner,
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
        pristine = git_show(root, relative)
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
