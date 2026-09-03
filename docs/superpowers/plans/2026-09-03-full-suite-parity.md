# Full OSWorld 1.0 Support and Docker Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run all official OSWorld 1.0 tasks on independent, parallel E2B sandboxes with complete attempt evidence and a pinned Qwen3-VL Docker comparison contract.

**Architecture:** Immutable support and parity profiles select exact upstream checkouts and verified task inventories. Every OSWorld provider instance owns a dynamically ported relay and sandbox, while a durable campaign coordinator schedules one authoritative upstream task per child process and records every state transition and artifact.

**Tech Stack:** Python 3.11+, aiohttp, E2B Python SDK, pytest, Bash, TypeScript, E2B Template SDK, JSON/JSONL, SHA-256.

**Spec:** `docs/superpowers/specs/2026-09-03-full-suite-parity-design.md`

## Global Constraints

- The sandbox is the VM; never run QEMU, KVM, VMware, or VirtualBox inside E2B.
- Preserve upstream task JSON, setup steps, getters, metrics, evaluators, and model action semantics.
- Pin `current-v1` to `fc31a9049664292fcb35d6e501ee1dc839f2cf6d` and `ui-mopd-qwen3vl-docker` to `fe8c78e15a1149e82d54137e9ffef18aee710ed7`.
- Require an immutable E2B `name:build_id` before sandbox creation.
- Keep proxy credentials, model API keys, Google credentials, raw trajectories, and generated run bundles out of Git.
- Keep sandbox and model-request caps independent and require explicit authorization before paid execution.
- Count agent-scored zero as valid; never convert missing or infrastructure-invalid attempts into zero.
- Use eight parallel task processes by default, bounded by the contract and explicit operator overrides.

---

### Task 1: Immutable upstream profiles and complete task inventories

**Files:**
- Create: `validation/profiles.json`
- Create: `validation/inventories/current-v1-all.json`
- Create: `validation/inventories/current-v1-nogdrive.json`
- Create: `validation/inventories/current-v1-gdrive.json`
- Create: `validation/inventories/ui-mopd-qwen3vl-docker-nogdrive.json`
- Create: `runner/profile.py`
- Create: `runner/build_inventory.py`
- Modify: `upstream.lock.json`
- Modify: `template/inputs.lock.json`
- Test: `tests/test_profiles.py`

**Interfaces:**
- Produces: `load_profiles(path: Path) -> dict`, `select_profile(name: str, path: Path) -> dict`, and `build_inventory(checkout: Path, profile: dict, suite: str) -> dict`.
- Produces: inventory entries shaped as `{"domain": str, "id": str, "task_sha256": str, "proxy": bool}` plus `task_count`, `inventory_sha256`, and `evaluator_tree_sha256`.

- [ ] **Step 1: Write failing profile and inventory tests**

```python
def test_current_profile_covers_the_complete_official_suites():
    profile = select_profile("current-v1", PROFILES)
    assert profile["commit"] == "fc31a9049664292fcb35d6e501ee1dc839f2cf6d"
    assert load_inventory("current-v1-all")["task_count"] == 369
    assert load_inventory("current-v1-nogdrive")["task_count"] == 361
    assert load_inventory("current-v1-gdrive")["task_count"] == 8


def test_profile_loader_rejects_mutable_and_malformed_commits(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text('{"profiles":{"bad":{"repository":"https://github.com/xlang-ai/OSWorld.git","commit":"main"}}}')
    with pytest.raises(ValueError, match="40 lowercase hexadecimal"):
        load_profiles(path)
```

- [ ] **Step 2: Run the focused tests and confirm they fail because the profile API is absent**

Run: `uv run pytest tests/test_profiles.py -q`

- [ ] **Step 3: Implement strict profile loading and inventory generation**

```python
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def select_profile(name: str, path: Path) -> dict:
    profiles = load_profiles(path)["profiles"]
    if name not in profiles:
        raise ValueError(f"unknown OSWorld profile: {name}")
    return profiles[name]
```

The generator reads only the selected upstream commit, resolves task IDs from the official suite
JSON, hashes each `evaluation_examples/examples/{domain}/{id}.json`, hashes the sorted evaluator
tree, and writes deterministic JSON. Generate `gdrive` as the ordered `all - nogdrive` difference.

- [ ] **Step 4: Generate inventories from clean detached upstream checkouts and verify counts**

Run: `uv run python runner/build_inventory.py --profiles validation/profiles.json --output-dir validation/inventories`

Expected: `current-v1` counts `369/361/8`; parity no-GDrive count `361`; every entry has a task SHA-256.

- [ ] **Step 5: Run profile tests and commit**

Run: `uv run pytest tests/test_profiles.py -q`

Commit: `feat: pin full OSWorld suite profiles`

---

### Task 2: Profile-aware deterministic upstream setup

**Files:**
- Modify: `runner/setup.sh`
- Modify: `runner/patch_upstream.py`
- Modify: `tests/test_setup.py`
- Modify: `tests/test_runner_setup.py`

**Interfaces:**
- Consumes: `runner/profile.py` and `validation/profiles.json` from Task 1.
- Produces: `runner/setup.sh --profile NAME [DEST]` and `patch_checkout(root, expected_commit)` compatible with both pinned upstream shapes.

- [ ] **Step 1: Add failing tests for current main, parity pin, unknown profile, and patch idempotence**

```python
@pytest.mark.parametrize("providers", [
    '{"fastvm", "pyromind", "modal"}',
    '{"fastvm", "pyromind", "modal", "daytona"}',
])
def test_desktop_patch_adds_e2b_to_supported_cloud_provider_sets(tmp_path, providers):
    checkout, head = checkout_fixture(tmp_path, providers)
    patch_checkout(checkout, head)
    assert '"e2b"' in (checkout / "desktop_env/desktop_env.py").read_text()
```

- [ ] **Step 2: Run the focused tests and confirm the current-main anchor fails**

Run: `uv run pytest tests/test_setup.py tests/test_runner_setup.py -q`

- [ ] **Step 3: Replace exact-list patching with syntax-bounded set insertion and add profile selection**

The transform must find the provider-membership set containing `fastvm` and insert `e2b` without
assuming which later providers exist. `setup.sh` obtains repository and commit from
`runner/profile.py`, fetches only that commit, checks origin, verifies inventory bytes, and then
copies the generated E2B adapter files.

- [ ] **Step 4: Prove both real upstream pins patch cleanly and idempotently**

Run: `runner/setup.sh --profile current-v1 /tmp/osworld-e2b-current`

Run: `runner/setup.sh --profile ui-mopd-qwen3vl-docker /tmp/osworld-e2b-parity`

Run each command a second time and confirm `git diff --binary HEAD` is unchanged.

- [ ] **Step 5: Run setup tests and commit**

Run: `uv run pytest tests/test_setup.py tests/test_runner_setup.py -q`

Commit: `feat: support pinned current and parity checkouts`

---

### Task 3: Provider-owned dynamic relay and sandbox isolation

**Files:**
- Create: `realkit/ports.py`
- Modify: `realkit/provider.py`
- Modify: `realkit/relay.py`
- Modify: `runner/run.sh`
- Modify: `tests/test_identity.py`
- Modify: `tests/test_relay.py`
- Create: `tests/test_provider.py`

**Interfaces:**
- Produces: `PortBundle(control: int, server: int, chromium: int, vlc: int)` and `reserve_port_bundle() -> PortBundle`.
- Produces: `E2BProvider.start_emulator()` that starts one relay child and `stop_emulator()` that always attempts relay and sandbox cleanup.
- Relay CLI consumes `--control-port`, `--server-port`, `--chromium-port`, `--vlc-port`, and `--event-log`.

- [ ] **Step 1: Add failing dynamic-port and provider-lifecycle tests**

```python
def test_two_providers_receive_disjoint_port_bundles():
    first = reserve_port_bundle()
    second = reserve_port_bundle()
    assert set(dataclasses.astuple(first)).isdisjoint(dataclasses.astuple(second))


def test_provider_reports_its_own_dynamic_endpoints(fake_relay):
    provider = E2BProvider()
    provider.start_emulator(IMMUTABLE_REF, True, "Ubuntu")
    assert provider.get_ip_address(IMMUTABLE_REF) == fake_relay.expected_ip_ports
    provider.stop_emulator(IMMUTABLE_REF)
    assert fake_relay.stopped
```

- [ ] **Step 2: Run the focused tests and confirm fixed global ports cause failure**

Run: `uv run pytest tests/test_provider.py tests/test_relay.py tests/test_identity.py -q`

- [ ] **Step 3: Make relay configuration instance-owned and emit sanitized lifecycle JSONL**

Refactor module globals into immutable `RelayConfig` passed to `GuestManager` and app factories.
Events include timestamp, event type, sandbox ID, generation, immutable template reference, source,
and cleanup outcome. They never include traffic tokens or environment values.

- [ ] **Step 4: Make each provider start and own its relay child**

Use `sys.executable`, an explicit relay path, a minimal inherited environment, pipes redirected to
the attempt log paths, and a bounded `/health` poll. On a failed start, terminate the relay and
surface its exit code. `run.sh` no longer starts a singleton relay; it invokes the selected upstream
runner with `--provider_name e2b`.

- [ ] **Step 5: Run lifecycle tests and commit**

Run: `uv run pytest tests/test_provider.py tests/test_relay.py tests/test_identity.py -q`

Commit: `feat: isolate one relay per OSWorld environment`

---

### Task 4: Durable task-attempt result ledger

**Files:**
- Create: `realkit/results.py`
- Create: `tests/test_results.py`

**Interfaces:**
- Produces: `RunLedger.create(root: Path, metadata: dict, tasks: list[TaskKey]) -> RunLedger`.
- Produces: `ledger.append(event: AttemptEvent)`, `ledger.terminal_tasks() -> set[TaskKey]`, `ledger.resume_candidates(max_attempts: int) -> list[TaskKey]`, and `ledger.aggregate() -> dict`.
- Produces terminal classifications `valid`, `runner_exit`, `timeout`, `missing_result`, `malformed_result`, `identity_drift`, `cleanup_failed`, and `interrupted`.

- [ ] **Step 1: Write failing state-machine and aggregation tests**

```python
def test_valid_zero_is_scored_while_missing_is_invalid(tmp_path):
    ledger = make_ledger(tmp_path, [TASK_A, TASK_B])
    ledger.append(started(TASK_A, 1))
    ledger.append(valid(TASK_A, 1, reward=0.0))
    ledger.append(started(TASK_B, 1))
    ledger.append(invalid(TASK_B, 1, "missing_result"))
    aggregate = ledger.aggregate()
    assert aggregate["valid"] == 1
    assert aggregate["invalid_by_reason"] == {"missing_result": 1}
    assert aggregate["score"] == 0.0
```

- [ ] **Step 2: Run the focused tests and confirm the ledger module is absent**

Run: `uv run pytest tests/test_results.py -q`

- [ ] **Step 3: Implement append-only events, atomic summaries, resume, and checksums**

Write each JSONL event with `flush()` and `os.fsync()`. Regenerate `aggregate.json` through a
same-directory temporary file followed by `os.replace()`. Reject illegal transitions, duplicate
terminal records, non-finite rewards, task keys outside the pinned inventory, and changed campaign
fingerprints.

- [ ] **Step 4: Cover crash recovery and bounded retry behavior**

Add tests proving an unmatched `STARTED` event is reported as missing, resumes as attempt 2, and
stops becoming eligible after `max_attempts`.

- [ ] **Step 5: Run result tests and commit**

Run: `uv run pytest tests/test_results.py -q`

Commit: `feat: record every OSWorld task attempt`

---

### Task 5: Parallel campaign coordinator

**Files:**
- Create: `runner/campaign.py`
- Create: `tests/fixtures/fake_osworld_runner.py`
- Create: `tests/test_campaign.py`
- Modify: `runner/run.sh`

**Interfaces:**
- Consumes: profiles from Task 1, provider isolation from Task 3, and `RunLedger` from Task 4.
- Produces CLI `runner/campaign.py --profile NAME --suite NAME --template NAME:BUILD_ID --runner PATH --num-envs N --result-root PATH -- [upstream args]`.
- Produces default `num_envs=8`, bounded by contract sandbox cap; each attempt gets one-task manifest, result directory, upstream log directory, relay event log, stdout, and stderr.

- [ ] **Step 1: Add failing fake-runner tests for concurrency and every terminal outcome**

```python
def test_campaign_runs_in_parallel_and_accounts_for_all_tasks(tmp_path):
    result = run_fake_campaign(tmp_path, tasks=12, num_envs=4)
    aggregate = json.loads((result / "aggregate.json").read_text())
    assert aggregate["planned"] == 12
    assert aggregate["terminal"] == 12
    assert aggregate["max_observed_children"] == 4
```

The fixture accepts an outcome map and emits valid zero, valid fractional reward, malformed result,
no result, nonzero exit, timeout, and delayed success deterministically.

- [ ] **Step 2: Run the focused tests and confirm the coordinator is absent**

Run: `uv run pytest tests/test_campaign.py -q`

- [ ] **Step 3: Implement bounded subprocess scheduling and signal-safe cleanup**

Use `asyncio.create_subprocess_exec` and a semaphore. Write `PLANNED` before launch and `STARTED`
immediately after obtaining the PID. On `SIGINT` or `SIGTERM`, terminate children, wait a bounded
interval, kill survivors, append `interrupted`, and rebuild the aggregate. Never use a shell command
string and never place secret values in recorded arguments.

- [ ] **Step 4: Implement upstream artifact discovery and immutable checksums**

Locate the single task's upstream result directory from the declared action-space, observation, and
model arguments. Parse `result.txt`, copy or retain all raw files under the attempt directory, write
`artifacts.json` with path, byte length, and SHA-256, and classify absent or malformed output without
deleting it.

- [ ] **Step 5: Run campaign tests and commit**

Run: `uv run pytest tests/test_campaign.py -q`

Commit: `feat: run OSWorld tasks in parallel with recovery`

---

### Task 6: Proxy and Google Drive preflight without secret retention

**Files:**
- Create: `realkit/preflight.py`
- Create: `tests/test_preflight.py`
- Modify: `runner/campaign.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `validate_capabilities(tasks, suite, proxy_config, secret_mounts) -> CapabilityEvidence`.
- Produces sanitized mounts as `{"guest_path": str, "source_sha256": str, "source_label": str}`.

- [ ] **Step 1: Add failing proxy, credential, and redaction tests**

```python
def test_proxy_tasks_reject_upstream_placeholder_credentials(tmp_path):
    proxy = tmp_path / "proxy.json"
    proxy.write_text('[{"host":"gw.dataimpulse.com","port":823,"username":"your_username","password":"your_password"}]')
    with pytest.raises(ValueError, match="placeholder proxy credentials"):
        validate_capabilities([PROXY_TASK], "nogdrive", proxy, [])


def test_secret_evidence_never_contains_host_path_or_bytes(tmp_path):
    secret = tmp_path / "google.json"
    secret.write_text('{"private_key":"secret"}')
    evidence = sanitize_mount(f"{secret}:/opt/osworld/secrets/google.json")
    assert str(secret) not in json.dumps(evidence)
    assert "secret" not in json.dumps(evidence)
```

- [ ] **Step 2: Run the focused tests and confirm preflight is absent**

Run: `uv run pytest tests/test_preflight.py -q`

- [ ] **Step 3: Implement capability checks and sanitized evidence**

Require a readable, non-placeholder proxy file if any selected inventory entry has `proxy=true`.
Require at least one valid `local_path:guest_path` mount for `all` or `gdrive`. Hash files before
launch, retain only the basename as `source_label`, and reject guest paths outside `/opt/osworld/secrets/`.

- [ ] **Step 4: Pass secret paths only through child environment and upstream mount arguments**

The in-memory child launch may contain the real paths; persisted `run.json`, events, stdout/stderr
command preambles, and errors use the sanitized mount representation. Redact proxy URL user-info,
API-key-shaped values, traffic tokens, and known secret source paths from captured text.

- [ ] **Step 5: Run preflight tests and commit**

Run: `uv run pytest tests/test_preflight.py -q`

Commit: `feat: enable proxy and credential task preflight`

---

### Task 7: Pinned Qwen reference and paid-run contract validator

**Files:**
- Create: `validation/reference/ui-mopd-qwen3vl-docker.json`
- Create: `validation/validation-contract.example.json`
- Create: `realkit/contract.py`
- Create: `tests/test_contract.py`
- Modify: `runner/campaign.py`

**Interfaces:**
- Produces: `load_contract(path: Path) -> ValidationContract` and `validate_contract(contract, profiles, inventory) -> None`.
- Reference records dataset commit `a518b8776c172c9456f85b3fa5ef451d326a7969`, model commit `3e6acbe78847870fc645786bfaf55c64bff84903`, 359 scored tasks, two missing task IDs, reward sum `132.79220946530714`, and 361-denominator score `0.36784545558256826`.

- [ ] **Step 1: Add failing contract completeness and score tests**

```python
def test_reference_uses_fractional_reward_over_declared_denominator():
    reference = json.loads(REFERENCE.read_text())
    assert reference["reward_sum"] / reference["denominator"] == pytest.approx(
        0.36784545558256826
    )
    assert len(reference["missing_tasks"]) == 2


def test_contract_rejects_mutable_template_and_shared_caps():
    contract = valid_contract(template="osworld-gnome", model_request_cap=None)
    with pytest.raises(ValueError):
        validate_contract(contract, PROFILES, INVENTORY)
```

- [ ] **Step 2: Run focused tests and confirm contract validation is absent**

Run: `uv run pytest tests/test_contract.py -q`

- [ ] **Step 3: Implement strict validation of identities, settings, caps, and arithmetic**

Require the exact profile and inventory digest, immutable template reference, authoritative runner,
model commit, non-secret endpoint labels, temperature 0, top-p 0.9, max tokens 2048, max steps 50,
bounded retries, task timeout, sandbox cap, and model-request cap. Ensure
`tasks * max_steps * model_call_attempts <= model_request_cap` and recompute reference scores.

- [ ] **Step 4: Make campaign execution require a valid non-example contract**

The example contract contains an explicit `execution_authorized: false` and non-runnable endpoint
labels. `runner/campaign.py` accepts it for `--preflight-only` but refuses execution until an
operator-created contract supplies an immutable template, concrete endpoint labels resolved from
the process environment, valid caps, and `execution_authorized: true`.

- [ ] **Step 5: Run contract tests and commit**

Run: `uv run pytest tests/test_contract.py -q`

Commit: `feat: pin Qwen Docker parity contract`

---

### Task 8: Documentation, source-of-truth fidelity ledger, and complete verification

**Files:**
- Modify: `README.md`
- Modify: `docs/FIDELITY.md`
- Modify: `docs/SOURCE.md`
- Modify: `runner/README.md`
- Modify: `validation/manifest.json`
- Modify: `validation/test_all_meta_e2b.json`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Documents exact support, parity, execution, resume, artifact, secret, cost, and limitation contracts.
- CI regenerates inventories in check mode and runs all offline campaign tests without E2B or model credentials.

- [ ] **Step 1: Replace the 24-task default and proxy exclusion claims with generated profile suites**

Document `current-v1` as default, the 369/361/8 census, the 52 proxy-required tasks, runtime proxy
and secret requirements, and the historical parity profile's inferred source limitation. Retain the
24-task manifest only as a named smoke lane rather than the claimed support boundary.

- [ ] **Step 2: Document parallel execution and result recovery commands**

```bash
runner/setup.sh --profile current-v1
runner/run.sh --profile current-v1 --suite nogdrive --num-envs 8 -- \
  --observation_type screenshot --model Qwen3-VL-8B-Thinking

uv run python runner/campaign.py --resume results/runs/20260903T120000Z-qwen-e2b
```

Explain that each environment has a private relay/port bundle and no guest resources are shared.

- [ ] **Step 3: Add CI inventory drift and offline campaign checks**

Run the generator with `--check` after setup fixtures, ensuring committed inventory bytes match the
pinned upstream commits. Keep all credentialed/live steps outside public CI.

- [ ] **Step 4: Run the complete repository verification suite**

Run: `uv run pytest -q`

Run: `uv run ruff check .`

Run: `uv run ruff format --check .`

Run: `scripts/audit_python_dependencies.sh`

Run: `npm ci && npm run typecheck && npm test`

Run: `python3 scripts/check_public_tree.py && python3 scripts/check_ci_policy.py`

Run: `runner/setup.sh --profile current-v1 /tmp/osworld-e2b-current-final`

Run: `runner/setup.sh --profile ui-mopd-qwen3vl-docker /tmp/osworld-e2b-parity-final`

- [ ] **Step 5: Run a no-cost full 361-task fake campaign and inspect accounting**

Expected: 361 planned, 361 terminal, no missing records, configured parallelism observed, all fake
sandboxes/relays marked cleaned, deterministic aggregate, and successful resume no-op.

- [ ] **Step 6: Commit documentation and verification changes**

Commit: `docs: publish full-suite execution contract`

- [ ] **Step 7: Stop before paid execution and present the exact authorization packet**

Report the immutable template build still required, endpoint deployment requirement, expected E2B
sandbox ceiling, worst-case model-request cap, retry budget, estimated cost inputs, and the exact
command that will run only after immediate explicit authorization.
