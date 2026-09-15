"""Validation-contract checks that gate paid OSWorld parity execution."""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

from .e2b_policy import require_immutable_template_ref

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
ENDPOINT_LABEL_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
EXPECTED_SETTINGS = {
    "action_space": "pyautogui",
    "coordinate_type": "relative",
    "max_steps": 50,
    "max_tokens": 2048,
    "max_trajectory_length": 3,
    "observation_type": "screenshot",
    "screen_height": 1080,
    "screen_width": 1920,
    "sleep_after_execution": 3,
    "temperature": 0,
    "top_p": 0.9,
}
REFERENCE_SCORE = 0.36784545558256826
REFERENCE_DATASET_COMMIT = "a518b8776c172c9456f85b3fa5ef451d326a7969"
MODEL_REPOSITORY = "UI-MOPD/Qwen3-VL-8B-Thinking-UI-MOPD-Student"
MODEL_COMMIT = "3e6acbe78847870fc645786bfaf55c64bff84903"


def load_contract(path: Path) -> dict:
    try:
        document = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"validation contract is not readable JSON: {path}") from error
    if document.get("schema_version") != 1:
        raise ValueError("validation contract schema_version must be 1")
    return document


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def validate_contract(
    contract: dict,
    profiles: dict,
    inventory: dict,
    *,
    for_execution: bool = False,
    environment: dict[str, str] | None = None,
) -> None:
    try:
        benchmark = contract["benchmark"]
        route = contract["route"]
        agent = contract["agent"]
        execution = contract["execution"]
        comparison = contract["comparison"]
    except KeyError as error:
        raise ValueError(f"validation contract missing section: {error.args[0]}") from error

    profile_name = benchmark.get("profile")
    profile = profiles.get("profiles", {}).get(profile_name)
    if profile is None:
        raise ValueError(f"unknown benchmark profile: {profile_name}")
    if benchmark.get("repository") != profile["repository"]:
        raise ValueError("benchmark repository does not match the profile")
    if benchmark.get("commit") != profile["commit"]:
        raise ValueError("benchmark commit does not match the profile")
    suite = benchmark.get("suite")
    if suite not in profile["suites"]:
        raise ValueError(f"benchmark suite is not declared by the profile: {suite}")
    if benchmark.get("task_count") != inventory.get("task_count"):
        raise ValueError("benchmark task_count does not match the inventory")
    if benchmark.get("inventory_sha256") != inventory.get("inventory_sha256"):
        raise ValueError("benchmark inventory checksum does not match the pinned inventory")
    if inventory.get("profile") != profile_name or inventory.get("suite") != suite:
        raise ValueError("inventory profile or suite identity does not match the benchmark")

    require_immutable_template_ref(route.get("template_ref"), "route.template_ref")
    if route.get("runner") != profile["runner"]:
        raise ValueError("route runner does not match the pinned profile runner")

    if agent.get("model_repository") != MODEL_REPOSITORY:
        raise ValueError("model repository does not match the pinned Qwen reference")
    if agent.get("model_commit") != MODEL_COMMIT or not COMMIT_RE.fullmatch(
        str(agent.get("model_commit", ""))
    ):
        raise ValueError("model commit does not match the pinned Qwen reference")
    settings = agent.get("settings", {})
    for field, expected in EXPECTED_SETTINGS.items():
        if settings.get(field) != expected:
            raise ValueError(f"agent {field} must equal the public reference value {expected}")
    endpoint_labels = agent.get("endpoint_env")
    if not isinstance(endpoint_labels, list) or not endpoint_labels:
        raise ValueError("agent endpoint_env must contain at least one environment label")
    if len(set(endpoint_labels)) != len(endpoint_labels) or not all(
        isinstance(label, str) and ENDPOINT_LABEL_RE.fullmatch(label) for label in endpoint_labels
    ):
        raise ValueError("agent endpoint_env values must be unique environment-variable labels")

    sandbox_cap = _positive_int(execution.get("sandbox_concurrency_cap"), "sandbox_concurrency_cap")
    model_cap = _positive_int(execution.get("model_request_cap"), "model_request_cap")
    attempts = _positive_int(execution.get("max_attempts_per_task"), "max_attempts_per_task")
    call_attempts = _positive_int(execution.get("model_call_attempts"), "model_call_attempts")
    _positive_int(execution.get("task_timeout_seconds"), "task_timeout_seconds")
    if sandbox_cap > benchmark["task_count"]:
        raise ValueError("sandbox_concurrency_cap cannot exceed the task count")
    worst_case_requests = benchmark["task_count"] * settings["max_steps"] * call_attempts * attempts
    if model_cap < worst_case_requests:
        raise ValueError(
            f"model_request_cap {model_cap} is below the worst-case bound {worst_case_requests}"
        )

    if profile_name == "ui-mopd-qwen3vl-docker":
        if comparison.get("mode") != "public_docker_parity":
            raise ValueError("parity comparison mode must be public_docker_parity")
        if comparison.get("reference_dataset_commit") != REFERENCE_DATASET_COMMIT:
            raise ValueError("comparison reference dataset commit does not match")
        if (
            comparison.get("reference_total_tasks") != 361
            or comparison.get("reference_scored_tasks") != 359
        ):
            raise ValueError("comparison reference task counts do not match")
        if not math.isclose(comparison.get("reference_score", -1), REFERENCE_SCORE, abs_tol=1e-15):
            raise ValueError("comparison reference score does not match")
        if comparison.get("absolute_score_delta_lte") != 0.03:
            raise ValueError("comparison acceptance band must equal 0.03")
    elif comparison != {"mode": "none"}:
        raise ValueError("current-suite contracts must disable historical comparison")

    if for_execution:
        if execution.get("execution_authorized") is not True:
            raise ValueError("execution_authorized must be true for paid execution")
        if route.get("final") is not True:
            raise ValueError("execution requires a final immutable route")
        available = os.environ if environment is None else environment
        missing = [label for label in endpoint_labels if not available.get(label)]
        if missing:
            raise ValueError(f"model endpoint environment is missing: {', '.join(missing)}")


def compare_results(
    e2b_results: dict[tuple[str, str], float],
    reference: dict,
    *,
    absolute_score_delta_lte: float,
) -> dict:
    reference_results = {
        (item["domain"], item["id"]): float(item["reward"]) for item in reference["task_results"]
    }
    missing_reference = {(item["domain"], item["id"]) for item in reference["missing_tasks"]}
    expected = set(reference_results) | missing_reference
    unexpected = set(e2b_results) - expected
    if unexpected:
        raise ValueError(
            f"E2B results contain tasks outside the reference suite: {sorted(unexpected)}"
        )
    if set(e2b_results) != expected:
        return {
            "ready": False,
            "required_tasks": reference["denominator"],
            "valid_tasks": len(e2b_results),
        }
    e2b_score = sum(e2b_results.values()) / reference["denominator"]
    reference_score = reference["reward_sum"] / reference["denominator"]
    common_e2b_sum = sum(e2b_results[key] for key in reference_results)
    common_reference_sum = sum(reference_results.values())
    absolute_delta = abs(e2b_score - reference_score)
    return {
        "ready": True,
        "required_tasks": reference["denominator"],
        "valid_tasks": len(e2b_results),
        "e2b_score": e2b_score,
        "reference_score": reference_score,
        "absolute_delta": absolute_delta,
        "acceptance_band": absolute_score_delta_lte,
        "accepted": absolute_delta <= absolute_score_delta_lte,
        "common_tasks": len(reference_results),
        "e2b_common_score": common_e2b_sum / len(reference_results),
        "reference_common_score": common_reference_sum / len(reference_results),
        "task_reward_agreements": sum(
            math.isclose(e2b_results[key], reward, abs_tol=1e-12)
            for key, reward in reference_results.items()
        ),
        "reference_missing_tasks": [
            {"domain": domain, "id": task_id} for domain, task_id in sorted(missing_reference)
        ],
        "reference_source_commit_provenance": reference["osworld_commit_provenance"],
    }
