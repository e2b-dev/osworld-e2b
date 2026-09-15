from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from realkit.contract import compare_results, load_contract, validate_contract
from runner.profile import load_inventory, load_profiles

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "validation" / "reference" / "ui-mopd-qwen3vl-docker.json"
EXAMPLE = ROOT / "validation" / "validation-contract.example.json"
FULL_EXAMPLE = ROOT / "validation" / "full-suite-contract.example.json"
PROFILES = ROOT / "validation" / "profiles.json"
INVENTORY = ROOT / "validation" / "inventories" / "ui-mopd-qwen3vl-docker-nogdrive.json"


def _documents() -> tuple[dict, dict, dict]:
    return load_contract(EXAMPLE), load_profiles(PROFILES), load_inventory(INVENTORY)


def test_reference_uses_fractional_reward_over_declared_denominator() -> None:
    reference = json.loads(REFERENCE.read_text())

    assert reference["summary_file_sha256"] == (
        "5757e864e1d61acc65c4233a5e64f8d33efb151c9913f92d210e8b25757c1ecd"
    )
    assert reference["scored_tasks"] == 359
    assert reference["denominator"] == 361
    assert reference["reward_sum"] / reference["denominator"] == pytest.approx(0.36784545558256826)
    assert len(reference["missing_tasks"]) == 2
    assert len(reference["task_results"]) == 359
    assert sum(item["reward"] for item in reference["task_results"]) == pytest.approx(
        reference["reward_sum"]
    )


def test_example_contract_is_complete_for_no_cost_preflight_but_not_execution() -> None:
    contract, profiles, inventory = _documents()

    validate_contract(contract, profiles, inventory, for_execution=False)
    with pytest.raises(ValueError, match="execution_authorized"):
        validate_contract(contract, profiles, inventory, for_execution=True)


def test_current_full_suite_contract_covers_all_369_tasks_without_historical_comparison() -> None:
    contract = load_contract(FULL_EXAMPLE)
    profiles = load_profiles(PROFILES)
    inventory = load_inventory(ROOT / "validation/inventories/current-v1-all.json")

    validate_contract(contract, profiles, inventory, for_execution=False)
    assert contract["benchmark"]["task_count"] == 369
    assert contract["comparison"] == {"mode": "none"}


def test_contract_rejects_mutable_template_and_shared_or_insufficient_caps() -> None:
    contract, profiles, inventory = _documents()
    contract["route"]["template_ref"] = "osworld-gnome"
    with pytest.raises(ValueError, match="immutable name:build_id"):
        validate_contract(contract, profiles, inventory)

    contract, profiles, inventory = _documents()
    contract["execution"]["model_request_cap"] = 100
    with pytest.raises(ValueError, match="model_request_cap"):
        validate_contract(contract, profiles, inventory)

    contract, profiles, inventory = _documents()
    del contract["execution"]["sandbox_concurrency_cap"]
    with pytest.raises(ValueError, match="sandbox_concurrency_cap"):
        validate_contract(contract, profiles, inventory)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("benchmark", "commit"), "0" * 40, "benchmark commit"),
        (("benchmark", "inventory_sha256"), "0" * 64, "inventory"),
        (("agent", "model_commit"), "0" * 40, "model commit"),
        (("agent", "settings", "temperature"), 1, "temperature"),
        (("agent", "settings", "max_steps"), 49, "max_steps"),
        (("comparison", "absolute_score_delta_lte"), 0.04, "acceptance"),
    ],
)
def test_contract_rejects_parity_identity_or_setting_drift(path, value, message) -> None:
    contract, profiles, inventory = _documents()
    target = contract
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ValueError, match=message):
        validate_contract(contract, profiles, inventory)


def test_execution_requires_final_route_and_resolved_endpoint_labels() -> None:
    contract, profiles, inventory = _documents()
    contract["execution"]["execution_authorized"] = True

    with pytest.raises(ValueError, match="final immutable route"):
        validate_contract(contract, profiles, inventory, for_execution=True)

    contract["route"]["final"] = True
    with pytest.raises(ValueError, match="QWEN_ENDPOINT_0"):
        validate_contract(
            contract,
            profiles,
            inventory,
            for_execution=True,
            environment={},
        )

    validate_contract(
        contract,
        profiles,
        inventory,
        for_execution=True,
        environment={"QWEN_ENDPOINT_0": "http://127.0.0.1:8000/v1"},
    )


def test_contract_loader_returns_independent_mutable_documents() -> None:
    first = load_contract(EXAMPLE)
    second = deepcopy(load_contract(EXAMPLE))
    first["benchmark"]["profile"] = "changed"

    assert second["benchmark"]["profile"] == "ui-mopd-qwen3vl-docker"


def test_reference_comparison_requires_complete_e2b_membership() -> None:
    reference = json.loads(REFERENCE.read_text())
    incomplete = {
        (item["domain"], item["id"]): item["reward"] for item in reference["task_results"]
    }

    pending = compare_results(incomplete, reference, absolute_score_delta_lte=0.03)

    assert pending == {"ready": False, "required_tasks": 361, "valid_tasks": 359}


def test_reference_comparison_reports_full_and_common_set_scores() -> None:
    reference = json.loads(REFERENCE.read_text())
    e2b = {(item["domain"], item["id"]): item["reward"] for item in reference["task_results"]}
    e2b.update({(item["domain"], item["id"]): 0.0 for item in reference["missing_tasks"]})

    comparison = compare_results(e2b, reference, absolute_score_delta_lte=0.03)

    assert comparison["ready"] is True
    assert comparison["e2b_score"] == pytest.approx(0.36784545558256826)
    assert comparison["reference_score"] == pytest.approx(0.36784545558256826)
    assert comparison["absolute_delta"] == pytest.approx(0.0)
    assert comparison["accepted"] is True
    assert comparison["common_tasks"] == 359


def _proxy(tmp_path: Path) -> Path:
    path = tmp_path / "proxy.json"
    path.write_text(
        '[{"host":"proxy.example","port":8080,"username":"account","password":"s3cret"}]'
    )
    return path


def test_campaign_cli_accepts_example_only_for_no_cost_preflight(tmp_path: Path) -> None:
    result_root = tmp_path / "runs"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "runner" / "campaign.py"),
            "--contract",
            str(EXAMPLE),
            "--preflight-only",
            "--proxy-config",
            str(_proxy(tmp_path)),
            "--result-root",
            str(result_root),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "PREFLIGHT_OK" in result.stdout
    assert not result_root.exists()


def test_campaign_cli_preflights_current_full_suite_capabilities(tmp_path: Path) -> None:
    result_root = tmp_path / "runs"
    secret = tmp_path / "google.json"
    secret.write_text('{"credential":"test-only"}')
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "runner" / "campaign.py"),
            "--contract",
            str(FULL_EXAMPLE),
            "--preflight-only",
            "--proxy-config",
            str(_proxy(tmp_path)),
            "--vm-secret-mount",
            f"{secret}:/opt/osworld/secrets/google.json",
            "--result-root",
            str(result_root),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    preflight = json.loads(result.stdout.removeprefix("PREFLIGHT_OK "))
    assert preflight["task_count"] == 369
    assert preflight["capabilities"]["proxy"]["required_task_count"] == 56
    assert len(preflight["capabilities"]["secret_mounts"]) == 1
    assert not result_root.exists()


def test_campaign_cli_refuses_unauthorized_contract_without_creating_a_run(
    tmp_path: Path,
) -> None:
    result_root = tmp_path / "runs"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "runner" / "campaign.py"),
            "--contract",
            str(EXAMPLE),
            "--proxy-config",
            str(_proxy(tmp_path)),
            "--result-root",
            str(result_root),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "execution_authorized" in result.stderr
    assert not result_root.exists()
