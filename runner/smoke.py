#!/usr/bin/env python3
"""Smoke-test an already-running OSWorld E2B relay and save evidence."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from e2b import Sandbox
from playwright.sync_api import sync_playwright

RELAY = "http://127.0.0.1:15000"
CDP = "http://127.0.0.1:19222"
CONTROL = "http://127.0.0.1:14999"
ROOT = Path(__file__).resolve().parent.parent


def request(url, *, method="GET", data=None, headers=None):
    body = None if data is None else json.dumps(data).encode()
    merged = {"Content-Type": "application/json"} if data is not None else {}
    merged.update(headers or {})
    try:
        with urlopen(
            Request(url, data=body, method=method, headers=merged), timeout=240
        ) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def relay_json(path, *, method="GET", data=None):
    status, body = request(f"{RELAY}{path}", method=method, data=data)
    if status != 200:
        raise RuntimeError(f"{path} returned HTTP {status}: {body[:500]!r}")
    return json.loads(body)


def accessibility():
    tree = relay_json("/accessibility").get("AT", "")
    if not tree:
        raise RuntimeError("accessibility tree was empty")
    return tree


def launch(command, wait_seconds):
    status, body = request(f"{RELAY}/setup/launch", method="POST", data={"command": command})
    if status != 200:
        raise RuntimeError(f"launch failed with HTTP {status}: {body[:500]!r}")
    time.sleep(wait_seconds)


def wait_for_cdp(timeout_seconds=30):
    deadline = time.monotonic() + timeout_seconds
    last_status, last_body = 0, b""
    while time.monotonic() < deadline:
        last_status, last_body = request(f"{CDP}/json/version")
        if last_status == 200:
            return json.loads(last_body)
        time.sleep(2)
    raise RuntimeError(
        f"CDP discovery did not become ready: HTTP {last_status}: {last_body[:500]!r}"
    )


def execute(command):
    return relay_json(
        "/execute",
        method="POST",
        data={
            "command": ["bash", "-lc", command],
            "shell": False,
        },
    )


def screenshot(name):
    status, body = request(f"{RELAY}/screenshot")
    if status != 200 or not body.startswith(b"\x89PNG"):
        raise RuntimeError(f"invalid screenshot {name}: HTTP {status}, {len(body)} bytes")
    (ROOT / "results" / name).write_bytes(body)
    return len(body)


def modal_absent(tree, phrases):
    lower = tree.lower()
    return not any(phrase in lower for phrase in phrases)


def named_dialog_absent(tree, names):
    alternatives = "|".join(re.escape(name) for name in names)
    return (
        re.search(rf'<(?:dialog|frame)[^>]*name="(?:{alternatives})"', tree, re.IGNORECASE) is None
    )


def main():
    if not os.environ.get("E2B_API_KEY"):
        raise RuntimeError("E2B_API_KEY is required")
    _, state_body = request(f"{CONTROL}/state")
    state = json.loads(state_body)
    sandbox = Sandbox.connect(state["sandbox_id"])
    token = sandbox.traffic_access_token
    if not token:
        raise RuntimeError("connected sandbox had no traffic access token")
    direct = f"https://{sandbox.get_host(5000)}/screen_size"
    unauth_status, _ = request(direct, method="POST")
    auth_status, _ = request(
        direct,
        method="POST",
        headers={
            "e2b-traffic-access-token": token,
        },
    )

    size = relay_json("/screen_size", method="POST")
    neutral_tree = accessibility()
    neutral_bytes = screenshot("smoke-neutral.png")
    version_command = """printf 'ubuntu='; . /etc/os-release; printf '%s\\n' "$VERSION_ID"
google-chrome --version
code --version | head -1
libreoffice --version
gimp --version | head -1
vlc --version | head -1
thunderbird --version
gnome-shell --version
python3 --version
if [ -e /dev/kvm ]; then echo kvm=present; else echo kvm=absent; fi"""
    version_response = execute(version_command)
    if version_response.get("returncode") != 0:
        raise RuntimeError(f"version query failed: {version_response}")
    versions = [line for line in version_response.get("output", "").splitlines() if line]

    execute("pkill -x chrome || true; pkill -x google-chrome || true")
    launch(["google-chrome"], 10)
    cdp_version = wait_for_cdp()
    websocket_url = cdp_version.get("webSocketDebuggerUrl", "")
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(CDP)
        cdp_contexts = len(browser.contexts)
        cdp_pages = sum(len(context.pages) for context in browser.contexts)
        browser.close()
    chrome_tree = accessibility()
    chrome_bytes = screenshot("smoke-chrome.png")

    execute("pkill -x chrome || true; pkill -x google-chrome || true")
    launch(["libreoffice", "--calc"], 10)
    libreoffice_tree = accessibility()
    libreoffice_bytes = screenshot("smoke-libreoffice.png")

    execute("pkill -x soffice.bin || true")
    launch(["vlc"], 8)
    vlc_tree = accessibility()
    vlc_bytes = screenshot("smoke-vlc.png")
    execute("pkill -x vlc || true")

    evidence = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "template": state["template"],
        "sandbox_id": state["sandbox_id"],
        "generation": state["generation"],
        "restricted_ingress": state["restricted_ingress"],
        "direct_unauthenticated_status": unauth_status,
        "direct_authenticated_status": auth_status,
        "screen_size": size,
        "neutral_screenshot_bytes": neutral_bytes,
        "accessibility_characters": len(neutral_tree),
        "versions": versions,
        "cdp_browser": cdp_version.get("Browser"),
        "cdp_websocket_rewritten_to_local_relay": websocket_url.startswith("ws://127.0.0.1:19222/"),
        "cdp_contexts": cdp_contexts,
        "cdp_pages": cdp_pages,
        "chrome_window_present": "google chrome" in chrome_tree.lower(),
        "chrome_keyring_modal_absent": modal_absent(chrome_tree, ("unlock login keyring",)),
        "chrome_screenshot_bytes": chrome_bytes,
        "libreoffice_window_present": "libreoffice calc" in libreoffice_tree.lower(),
        # First-run labels also occur in normal menus and hidden controls, so
        # only a top-level dialog/frame with one of these names is a failure.
        "libreoffice_first_run_modal_absent": named_dialog_absent(
            libreoffice_tree, ("tip of the day", "welcome to libreoffice")
        ),
        "libreoffice_screenshot_bytes": libreoffice_bytes,
        "vlc_window_present": "vlc media player" in vlc_tree.lower(),
        "vlc_privacy_modal_absent": modal_absent(
            vlc_tree, ("privacy and network access policy", "metadata network access")
        ),
        "vlc_screenshot_bytes": vlc_bytes,
    }
    checks = {
        "restricted ingress enabled": evidence["restricted_ingress"] is True,
        "unauthenticated ingress rejected": unauth_status == 403,
        "authenticated ingress accepted": auth_status == 200,
        "screen is 1920x1080": size == {"width": 1920, "height": 1080},
        "CDP websocket is relay-local": evidence["cdp_websocket_rewritten_to_local_relay"],
        "CDP attached to a context": cdp_contexts >= 1 and cdp_pages >= 1,
        "Chrome window present": evidence["chrome_window_present"],
        "Chrome first-run modal absent": evidence["chrome_keyring_modal_absent"],
        "LibreOffice window present": evidence["libreoffice_window_present"],
        "LibreOffice first-run modal absent": evidence["libreoffice_first_run_modal_absent"],
        "VLC window present": evidence["vlc_window_present"],
        "VLC privacy modal absent": evidence["vlc_privacy_modal_absent"],
    }
    evidence["checks"] = checks
    evidence["all_checks_passed"] = all(checks.values())
    (ROOT / "results" / "live-smoke.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(evidence, indent=2, sort_keys=True))
    if not evidence["all_checks_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
