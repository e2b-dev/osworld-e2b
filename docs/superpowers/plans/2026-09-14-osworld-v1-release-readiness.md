# OSWorld 1.0 Release Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the implemented OSWorld 1.0 E2B port into a reproducible, fidelity-validated integration whose complete supported suites and same-model comparison satisfy explicit release gates.

**Architecture:** Keep upstream OSWorld task, setup, action, and evaluator behavior authoritative while correcting the host bootstrap, E2B lifecycle ownership, and reconstructed desktop state at their existing adapter boundaries. Verification progresses from clean installation and deterministic desktop controls through proxy and credential paths to the complete real-agent comparison; partial samples remain diagnostic and cannot promote the release.

**Tech Stack:** Python 3.12, uv, pytest, aiohttp, E2B Python SDK 2.33.0, E2B Template SDK, TypeScript, Bash, GNOME 42/X11, OSWorld, Fireworks MiniMax M3, JSON/JSONL, SHA-256.

**Spec:** `docs/superpowers/specs/2026-09-03-full-suite-parity-design.md`

## Global Constraints

- The sandbox is the virtual machine; never run QEMU, KVM, VMware, VirtualBox, or Docker inside E2B.
- Pin supported upstream source to `xlang-ai/OSWorld@fc31a9049664292fcb35d6e501ee1dc839f2cf6d` until a separately reviewed profile update replaces it.
- Preserve upstream task JSON, setup steps, action semantics, getters, metrics, evaluators, and result arithmetic.
- Launch only immutable E2B `template:build_id` references and include every behavior-affecting build input in the recipe identity.
- Use one relay and one sandbox owner per OSWorld environment; default campaign concurrency remains eight and never introduces shared guest state.
- Keep API keys, proxy credentials, Google credentials, traffic tokens, raw trajectories, screenshots, and recordings out of Git.
- Count a task only when the authoritative evaluator returns a finite reward and cleanup evidence is complete; zero reward is valid, while missing or infrastructure-invalid output is not.
- Treat the ten-task MiniMax result as a diagnostic sample, not a full-suite score estimate or release comparison.
- Do not describe the integration as validated or publishable until the complete comparison and release review pass.

---

## Established merge foundation

The following requirements are implemented and remain mandatory CI gates for the integration.

### Task 1: Reproducible Python 3.12 OSWorld runtime

**Files:**
- Create: `runner/runtime-contract.json`
- Create: `tests/test_runtime_contract.py`
- Modify: `README.md`
- Modify: `runner/README.md`
- Modify: `runner/setup.sh`
- Modify: `runner/requirements-e2b.txt`
- Modify: `runner/campaign.py`
- Modify: `runner/minimax_sample.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_campaign.py`
- Modify: `tests/test_runner_setup.py`

**Interfaces:**
- Produces: `runner/setup.sh --profile NAME [DEST]`, with a Python 3.12 environment at `DEST/.venv` created from the pinned upstream lock.
- Produces: `execute_campaign(..., python_executable: Path, ...) -> RunLedger`; every child uses the declared OSWorld interpreter rather than the coordinator interpreter.
- Produces: runtime identity in `run.json` containing exact Python, Anthropic, OSWorld, E2B SDK, and runner identities.

- [x] **Step 1: Write failing runtime-contract tests**

```python
def test_supported_runtime_is_exact():
    contract = json.loads((ROOT / "runner/runtime-contract.json").read_text())
    assert contract["python"] == ">=3.12,<3.13"
    assert contract["anthropic"] == "0.84.0"
    assert contract["e2b"] == "2.33.0"


@pytest.mark.asyncio
async def test_campaign_uses_declared_osworld_interpreter(tmp_path):
    interpreter = tmp_path / "OSWorld" / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(sys.executable)
    ledger = await execute_fixture_campaign(tmp_path, python_executable=interpreter)
    assert str(interpreter) in read_started_command(ledger)
```

- [x] **Step 2: Run the focused tests and verify the missing contract and `sys.executable` launch fail**

Run: `uv run pytest tests/test_runtime_contract.py tests/test_campaign.py -q`

Expected: FAIL because the runtime contract and `python_executable` parameter do not exist.

- [x] **Step 3: Pin and install the supported host runtime**

`runner/runtime-contract.json` requires Python `>=3.12,<3.13`, Anthropic `0.84.0`, and E2B `2.33.0`. Setup initializes the pinned upstream submodules through HTTPS and runs `uv sync --project "$DEST" --frozen`. Frozen mode consumes the exact committed upstream lock because the pinned upstream commit added Daytona and Volcengine declarations without refreshing that lock; those providers are outside the E2B execution path. Setup then adds the pinned E2B adapter requirements and verifies:

```bash
"$DEST/.venv/bin/python" -c 'import anthropic, sys; assert sys.version_info[:2] == (3, 12); assert anthropic.__version__ == "0.84.0"'
```

Do not install OSWorld's unpinned `requirements.txt` into the repository development environment.

- [x] **Step 4: Pass the selected interpreter into every child**

Add the required keyword argument:

```python
async def execute_campaign(
    *,
    python_executable: Path,
    run_root: Path,
    inventory: dict,
    metadata: dict,
    runner: Path,
    osworld_root: Path,
    template: str,
    task_timeout_seconds: float,
    max_attempts: int,
    num_envs: int = DEFAULT_NUM_ENVS,
    upstream_args: tuple[str, ...] | list[str] = (),
    child_environment: dict[str, str] | None = None,
    proxy_config: Path | None = None,
    secret_mounts: tuple[str, ...] | list[str] = (),
    model_endpoints: tuple[str, ...] | list[str] = (),
) -> RunLedger:
```

Resolve it once, require an executable file, use it as `command[0]`, and put its version identity in the campaign fingerprint before creating a sandbox.

- [x] **Step 5: Add clean-install CI coverage**

Use Python 3.12, run setup in a temporary checkout, execute the interpreter identity probe, and run MiniMax `--preflight-only`. Keep credentialed execution outside CI.

- [x] **Step 6: Verify and commit**

Run: `uv run pytest tests/test_runtime_contract.py tests/test_campaign.py tests/test_runner_setup.py -q`

Run: `uv run pytest -q`

Expected: all tests pass and changing any runtime identity changes the campaign fingerprint.

```bash
git add README.md runner .github/workflows/ci.yml tests/test_campaign.py \
  tests/test_runner_setup.py tests/test_runtime_contract.py
git commit -m "fix: pin the OSWorld execution runtime"
```

### Task 2: Safe profile switching and one canonical checkout path

**Files:**
- Modify: `runner/setup.sh`
- Modify: `runner/patch_upstream.py`
- Modify: `runner/campaign.py`
- Modify: `runner/minimax_sample.py`
- Modify: `runner/README.md`
- Modify: `tests/test_setup.py`
- Modify: `tests/test_runner_setup.py`
- Modify: `tests/test_minimax_sample.py`

**Interfaces:**
- Produces: `restore_owned_patch(root: Path) -> None`, restoring only generated E2B changes after rejecting unrelated modifications.
- Produces: one default checkout path, `runner/OSWorld`, shared by setup, campaign, MiniMax, and documentation.

- [x] **Step 1: Add a failing real-Git profile-switch test**

```python
def test_setup_switches_profiles_in_one_owned_checkout(tmp_path):
    checkout = tmp_path / "OSWorld"
    run_setup("current-v1", checkout)
    run_setup("ui-mopd-qwen3vl-docker", checkout)
    assert git(checkout, "rev-parse", "HEAD") == HISTORICAL_COMMIT
    run_setup("current-v1", checkout)
    assert git(checkout, "rev-parse", "HEAD") == CURRENT_COMMIT
```

- [x] **Step 2: Verify the current generated patch blocks checkout**

Run: `uv run pytest tests/test_runner_setup.py::test_setup_switches_profiles_in_one_owned_checkout -q`

Expected: FAIL with Git's local-changes checkout error.

- [x] **Step 3: Restore only adapter-owned state before switching**

Have `restore_owned_patch` write pristine `HEAD:<path>` bytes to each `OWNED_TRACKED_PATHS` entry and remove only `OWNED_UNTRACKED_FILES` and `OWNED_UNTRACKED_PREFIXES`. First reject every changed or untracked path outside those allowlists. Call it before `git checkout --detach "$PIN"`; never use force checkout, hard reset, or broad clean.

- [x] **Step 4: Align all default checkout paths**

Use:

```python
parser.add_argument("--osworld-root", type=Path, default=root / "runner" / "OSWorld")
```

Update the runner guide so setup and execution work without undocumented path overrides.

- [x] **Step 5: Verify both directions, idempotence, and unrelated-change rejection**

Run: `uv run pytest tests/test_setup.py tests/test_runner_setup.py tests/test_minimax_sample.py -q`

Run setup in a new temporary directory in this order: current, historical, historical, current. Expected: every invocation exits zero and the generated diff is deterministic.

- [x] **Step 6: Commit**

```bash
git add runner/setup.sh runner/patch_upstream.py runner/campaign.py \
  runner/minimax_sample.py runner/README.md tests/test_setup.py \
  tests/test_runner_setup.py tests/test_minimax_sample.py
git commit -m "fix: make pinned OSWorld profiles reproducible"
```

Tasks 1 and 2 remain merge requirements. CI performs a clean runtime installation, MiniMax
preflight, historical-profile switch, idempotent repeat, and switch back to the current profile.

---

## Remaining fidelity work

### Task 3: Reference-equivalent resources and deterministic packages

**Files:**
- Create: `template/packages.lock.json`
- Create: `scripts/verify_template_packages.py`
- Create: `tests/test_template_packages.py`
- Modify: `template/build.ts`
- Modify: `template/identity.ts`
- Modify: `template/inputs.lock.json`
- Modify: `template/template.ts`
- Modify: `tests/test_build_identity.ts`
- Modify: `docs/FIDELITY.md`

**Interfaces:**
- Produces: a 4-vCPU, 16,384-MiB default matching the public reference resource class.
- Produces: package-lock entries with package name, exact version, immutable source, and SHA-256 for standalone artifacts.
- Produces: `verify_template_packages(receipt: dict, lock: dict) -> list[str]`.

- [ ] **Step 1: Write failing resource and identity tests**

```typescript
test('default resources match the OSWorld reference', () => {
  expect(buildResourcesFromEnvironment({})).toEqual({ cpuCount: 4, memoryMB: 16384 })
})

test('package lock participates in recipe identity', async () => {
  const before = await computeRecipeIdentity(fixtureRoot, { cpuCount: 4, memoryMB: 16384 })
  mutateFixture('template/packages.lock.json')
  const after = await computeRecipeIdentity(fixtureRoot, { cpuCount: 4, memoryMB: 16384 })
  expect(after.digest).not.toEqual(before.digest)
})
```

- [ ] **Step 2: Verify the current 8,192-MiB and rolling-input behavior fails**

Run: `npm test && uv run pytest tests/test_template_packages.py -q`

- [ ] **Step 3: Pin desktop artifacts and make them identity inputs**

Lock Ubuntu repository snapshot state and exact GNOME, LibreOffice, GIMP, VLC, font, and X11 versions. Lock Chrome and VS Code downloads by exact version and SHA-256. A lock change must change the template recipe digest.

- [ ] **Step 4: Build and verify a fresh immutable template**

Build with cache disabled, retain the new `name:build_id`, query all installed versions inside a fresh sandbox, and run the verifier. Expected: no package drift and a 4-vCPU/16,384-MiB receipt.

- [ ] **Step 5: Commit**

```bash
git add template scripts/verify_template_packages.py tests/test_build_identity.ts \
  tests/test_template_packages.py docs/FIDELITY.md
git commit -m "fix: pin the OSWorld desktop image"
```

### Task 4: Deterministic GNOME and application state

**Files:**
- Create: `template/files/seed-desktop-state.sh`
- Create: `runner/desktop_state_probe.py`
- Create: `validation/reference/desktop-state.json`
- Create: `tests/test_desktop_state.py`
- Modify: `template/files/dconf-osworld`
- Modify: `template/files/session_inner.sh`
- Modify: `docs/FIDELITY.md`

**Interfaces:**
- Produces: `runner/desktop_state_probe.py --output PATH`, recording screen geometry, `wmctrl -lxG`, dock settings, active window, and sanitized screenshots.
- Produces: a neutral desktop snapshot whose dock, scaling, fonts, and per-application initial geometry match retained reference state.

- [ ] **Step 1: Codify the public Chrome and GIMP initial-state contract**

Record full-screen dimensions, maximized state, dock visibility, active window class, scale, and theme in `validation/reference/desktop-state.json`, without user or task content.

- [ ] **Step 2: Write failing state assertions**

```python
def test_chrome_initial_state_matches_reference(probe):
    chrome = probe.window("google-chrome.Google-chrome")
    assert chrome.maximized is True
    assert chrome.width == 1920
    assert probe.dock.fixed is True


def test_gimp_initial_state_matches_reference(probe):
    assert probe.window("gimp.Gimp").maximized is True
```

- [ ] **Step 3: Prove the current template exhibits the known mismatch**

Run the probe on the retained template. Expected: Chrome and GIMP geometry or maximization and dock-state checks fail.

- [ ] **Step 4: Seed the reference state during template first boot**

Set dash-to-dock keys explicitly, open each supported app once, wait by window class, apply reference geometry with `wmctrl`, close cleanly to persist its profile, and leave the desktop neutral before readiness succeeds. Restored sandboxes inherit this state and do not repeat seeding.

- [ ] **Step 5: Verify fresh and reset state**

Probe a fresh sandbox and ten consecutive resets. Expected: every state matches the reference, screenshots are 1920×1080, and no task mutation survives reset.

- [ ] **Step 6: Commit**

```bash
git add template/files runner/desktop_state_probe.py validation/reference/desktop-state.json \
  tests/test_desktop_state.py docs/FIDELITY.md
git commit -m "fix: reproduce OSWorld desktop window state"
```

### Task 5: Timeout cleanup, ownership reconciliation, and metrics

**Files:**
- Modify: `realkit/relay.py`
- Modify: `realkit/provider.py`
- Modify: `runner/campaign.py`
- Modify: `realkit/results.py`
- Modify: `tests/fixtures/fake_osworld_runner.py`
- Modify: `tests/test_campaign.py`
- Modify: `tests/test_provider.py`
- Modify: `tests/test_relay.py`

**Interfaces:**
- Produces sandbox metadata keys `workload`, `run_id`, `domain`, `task_id`, `attempt`, and `generation` on every create.
- Produces reconciliation fields `owned_sandboxes_found`, `owned_sandboxes_killed`, `owned_sandboxes_remaining`, plus sampled CPU/RAM metrics.

- [ ] **Step 1: Add a failing timeout test with a child relay process**

Make the fixture spawn a process that records create/cleanup events and blocks until signaled. Assert timeout leaves no child process and no unmatched sandbox ID.

- [ ] **Step 2: Verify parent-only five-second termination is insufficient**

Run: `uv run pytest tests/test_campaign.py::test_timeout_reaps_runner_relay_and_owned_sandbox -q`

- [ ] **Step 3: Make process and sandbox ownership explicit**

Start each task in a process group, send SIGTERM to the group, allow the upstream cleanup handler its declared interval, then SIGKILL survivors. Pass sanitized ownership fields to the relay and `Sandbox.create(metadata=...)`.

- [ ] **Step 4: Reconcile owned sandboxes and capture resource evidence**

List by exact run metadata, kill every remaining owned sandbox, and refuse a valid aggregate while `owned_sandboxes_remaining` is nonzero. Capture `Sandbox.get_metrics` for peak RAM/CPU without retaining secrets.

- [ ] **Step 5: Verify and commit**

Run: `uv run pytest tests/test_campaign.py tests/test_provider.py tests/test_relay.py tests/test_results.py -q`

Execute live normal-completion, forced-timeout, SIGINT, ten-reset, snapshot-revert, and cleanup probes. Expected: every create has a clean and reconciliation finds zero resources.

```bash
git add realkit runner/campaign.py tests/fixtures/fake_osworld_runner.py \
  tests/test_campaign.py tests/test_provider.py tests/test_relay.py
git commit -m "fix: reconcile every OSWorld sandbox lifecycle"
```

---

## Release verification work

### Task 6: Authoritative proxy and Google Drive probes

**Files:**
- Create: `validation/manifests/current-v1-proxy-probe.json`
- Create: `validation/manifests/current-v1-gdrive-probe.json`
- Create: `validation/evidence/current-v1-capability-probes.json`
- Modify: `runner/validate.sh`
- Modify: `docs/FIDELITY.md`

**Interfaces:**
- Produces at least one unchanged upstream `proxy=true` task and at least one of the eight Drive tasks using `/opt/osworld/secrets/`.

- [ ] **Step 1: Generate manifests from the pinned inventory**

Record domain, task ID, task SHA-256, evaluator-tree SHA-256, proxy flag, and credential class.

- [ ] **Step 2: Execute negative controls**

Verify proxy tasks reject missing or placeholder configuration before sandbox creation. Verify Drive tasks reject a missing mount or a guest destination outside `/opt/osworld/secrets/`.

- [ ] **Step 3: Execute positive path controls**

Supply real credentials only at runtime. Execute reset, upstream setup, observation, a reversible action, authoritative evaluator, and cleanup. Retain sanitized identities and counts, not credential bytes or authenticated screenshots.

- [ ] **Step 4: Execute all eight Drive tasks with the real agent**

Expected: eight valid evaluator outputs, no infrastructure-invalid task, zero credential-byte hits, and zero remaining owned sandboxes.

- [ ] **Step 5: Commit the sanitized receipt**

```bash
git add validation/manifests validation/evidence/current-v1-capability-probes.json \
  runner/validate.sh docs/FIDELITY.md
git commit -m "test: validate OSWorld proxy and Drive paths"
```

### Task 7: Repeat the diverse MiniMax diagnostic

**Files:**
- Create: `validation/evidence/minimax-m3-e2b-diverse-10-rerun.json`
- Modify: `docs/FIDELITY.md`

**Interfaces:**
- Consumes the exact ten task IDs and public rewards in `validation/reference/minimax-m3-osworld-verified-sample.json`.
- Preserves the original `0.20` result as evidence rather than replacing it.

- [ ] **Step 1: Preflight exact source, task, template, runtime, and protocol identities**

Require Python 3.12, Anthropic 0.84.0, 1920×1080 relative pyautogui, 100 steps, 8,192 tokens, temperature 1, and eight-way concurrency.

- [ ] **Step 2: Execute all ten tasks once**

Do not retry a valid zero. Retry infrastructure-invalid attempts only within the declared cap and retain the original invalid evidence.

- [ ] **Step 3: Audit results**

Require ten valid evaluator outputs, zero missing tasks, complete checksums, zero model transport errors, matching sandbox create/clean IDs, zero remaining resources, and zero credential-byte hits.

- [ ] **Step 4: Compare diagnostically**

Report score delta, reward agreement, step counts, initial desktop-state comparison, and the AWS/adaptive-thinking limitation. A repeated systematic window mismatch returns to the deterministic GNOME and application state task.

- [ ] **Step 5: Commit**

```bash
git add validation/evidence/minimax-m3-e2b-diverse-10-rerun.json docs/FIDELITY.md
git commit -m "test: rerun the MiniMax fidelity sample"
```

### Task 8: Complete same-model no-Google-Drive comparison

**Files:**
- Create: `validation/contracts/minimax-m3-current-v1-nogdrive.json`
- Create: `validation/evidence/minimax-m3-current-v1-nogdrive.json`
- Modify: `realkit/contract.py`
- Modify: `tests/test_contract.py`
- Modify: `docs/FIDELITY.md`
- Modify: `README.md`

**Interfaces:**
- Produces a 361-task E2B contract with a primary 358-task public common set and explicit public omissions.
- Recomputes every aggregate from per-task evaluator rewards.

- [ ] **Step 1: Write failing MiniMax completeness tests**

```python
def test_minimax_comparison_requires_complete_e2b_and_common_set():
    comparison = compare_minimax_results(contract, e2b_results, public_results)
    assert comparison["e2b_valid_tasks"] == 361
    assert comparison["public_common_tasks"] == 358
    assert comparison["missing_public_tasks"] == 3


def test_minimax_contract_rejects_runtime_drift():
    with pytest.raises(ValueError, match="runtime identity"):
        validate_contract(contract_with(anthropic="1.4.0"), profiles, inventory)
```

- [ ] **Step 2: Verify the current contract lacks MiniMax completeness**

Run: `uv run pytest tests/test_contract.py -q`

- [ ] **Step 3: Declare comparison identities and tolerance before running**

Pin model endpoint, runner/prompt, inference settings, source/task hashes, grader, template, runtime, timeouts, retries, 361-task denominator, 358-task common set, archive hash, and absolute aggregate tolerance `0.03`. Retain the AWS/adaptive-thinking limitation.

- [ ] **Step 4: Execute all 361 E2B tasks**

Run eight sandboxes in parallel unless measured account or endpoint limits require a lower declared cap. Do not narrow the inventory after outcomes are visible.

- [ ] **Step 5: Recompute and apply the gate**

Require 361 valid E2B results. Compute full and common-set means, absolute deltas, per-domain scores, invalid attempts, peak resources, checksums, model errors, and cleanup. Pass only if common-set delta is at most `0.03`, no infrastructure-invalid task remains, and no unexplained domain regression indicates environment behavior.

- [ ] **Step 6: Commit the sanitized complete receipt**

```bash
git add validation/contracts/minimax-m3-current-v1-nogdrive.json \
  validation/evidence/minimax-m3-current-v1-nogdrive.json \
  realkit/contract.py tests/test_contract.py docs/FIDELITY.md README.md
git commit -m "test: verify complete MiniMax OSWorld parity"
```

### Task 9: Machine release gate and independent review

**Files:**
- Create: `validation/release/current-v1.json`
- Create: `scripts/validate_release.py`
- Create: `tests/test_release.py`
- Modify: `README.md`
- Modify: `docs/FIDELITY.md`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: `validate_release(path: Path) -> list[str]`, returning no errors only when all source, build, capability, comparison, security, and cleanup evidence is present and hash-valid.

- [ ] **Step 1: Write failing release tests**

```python
def test_release_rejects_diagnostic_only_evidence():
    errors = validate_release(fixture_release(comparison="diagnostic_sample"))
    assert "complete real-agent comparison required" in errors


def test_release_requires_drive_evidence():
    errors = validate_release(fixture_release(gdrive_valid_tasks=0))
    assert "Google Drive capability evidence required" in errors
```

- [ ] **Step 2: Verify the validator is absent**

Run: `uv run pytest tests/test_release.py -q`

- [ ] **Step 3: Implement the release gate**

Validate source and inventories, immutable template and package lock, runtime identity, desktop state, proxy/Drive receipts, 361-task completeness, archive checksum, score arithmetic/tolerance, zero unresolved infrastructure-invalid tasks, artifact checksums, credential scan, resource limits, and zero unmatched sandboxes.

- [ ] **Step 4: Run all repository gates**

Run: `uv run ruff check .`

Run: `uv run ruff format --check .`

Run: `uv run pytest -q`

Run: `scripts/audit_python_dependencies.sh`

Run: `npm ci && npm run typecheck && npm test && npm audit --omit=dev --audit-level=high`

Run: `bash -n runner/*.sh scripts/*.sh template/files/*.sh`

Run: `python3 scripts/check_public_tree.py && python3 scripts/check_ci_policy.py`

Run: `python3 scripts/validate_release.py validation/release/current-v1.json`

Expected: every command exits zero and the release validator reports no findings.

- [ ] **Step 5: Independently review underlying evidence**

Recompute score and checksum samples from raw artifacts, verify real model responses and authoritative graders, compare environment/resource/protocol identities, review secret handling, and confirm the E2B account has no sandbox owned by the campaign.

- [ ] **Step 6: Publish only after both gates pass**

Change documentation from “implemented” to “validated” only when the machine gate and independent review have no blockers. Keep raw evidence in protected storage and publish only sanitized receipts and immutable links.

- [ ] **Step 7: Commit**

```bash
git add validation/release/current-v1.json README.md docs/FIDELITY.md \
  .github/workflows/ci.yml scripts/validate_release.py tests/test_release.py
git commit -m "feat: validate the OSWorld current-v1 release"
```

## Merge boundary

PR #1 may merge as an explicitly experimental, implemented integration when its required CI is
green. It must not be described as fidelity-validated, Docker-equivalent, or publishable until
Tasks 3 through 9 pass. If maintainers require the initial merge to contain a validated release
rather than experimental integration code, the remaining tasks also become pre-merge requirements.
