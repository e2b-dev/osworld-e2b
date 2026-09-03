# OSWorld 1.0 on E2B

This repository runs the official OSWorld 1.0 desktop benchmark on native E2B sandboxes. E2B is
the VM boundary: the port does not run the upstream qcow2 image, QEMU, KVM, VMware, VirtualBox, or
Docker inside a sandbox. It reconstructs the Ubuntu 22.04 GNOME desktop as an immutable E2B
Template and keeps OSWorld's task definitions, setup logic, actions, getters, metrics, and
evaluators authoritative.

Two immutable upstream profiles serve different purposes:

- `current-v1` is the default support profile. It pins official OSWorld commit
  `fc31a9049664292fcb35d6e501ee1dc839f2cf6d` and exposes all 369 tasks, the 361-task
  no-Google-Drive suite, and the eight-task Google Drive difference.
- `ui-mopd-qwen3vl-docker` reproduces the environment and agent configuration needed to compare
  against the public UI-MOPD Qwen3-VL Docker result. It pins OSWorld commit
  `fe8c78e15a1149e82d54137e9ffef18aee710ed7` and its 361-task no-Google-Drive inventory.
  The public run did not record its OSWorld SHA, so this historical source match is inferred from
  the run date and official main history, not authenticated by the result bundle.

`validation/profiles.json` and the generated inventories are the machine-readable source of truth.
Every task file and evaluator tree is checksummed. `runner/setup.sh` verifies the selected checkout
before applying the generated E2B adapter patch.

## Execution model

The coordinator schedules one authoritative OSWorld task per child process. Each process creates
one `DesktopEnv`, and each environment owns a private relay subprocess, dynamic port bundle,
sandbox, traffic token, log directory, and result directory. There are no shared guest resources.
Eight tasks run in parallel by default because sandbox isolation makes task-level parallelism the
normal mode; the validated contract and `--num-envs` can impose a lower cap. Model endpoints have a
separate request cap and can be supplied as multiple environment-variable labels for round-robin
distribution.

Every attempt is retained under ignored `results/runs/<run-id>/` storage. `attempts.jsonl` records
`PLANNED`, `STARTED`, and terminal events; per-attempt directories retain stdout, stderr, upstream
logs, screenshots, trajectories, recordings, evaluator results, relay lifecycle events, and an
artifact checksum catalog when produced. `aggregate.json` distinguishes valid zero reward from
timeouts, crashes, missing or malformed output, identity drift, failed cleanup, and interruption.
Re-running the same contract with the same `--run-id` resumes eligible tasks without deleting old
attempts.

## Build and offline verification

Python 3.11+, Node.js 20+, `uv`, and npm are required.

```bash
uv sync --locked --all-groups
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
scripts/audit_python_dependencies.sh
npm ci
npm run typecheck
npm test
python3 scripts/check_public_tree.py
python3 scripts/check_ci_policy.py
```

Builds are content-named from declared inputs but are not claimed byte-reproducible because some
Ubuntu, Chrome, and VS Code artifacts resolve at build time. Only the build receipt's
`name:build_id` identifies an immutable runnable E2B artifact.

## Full current suite

The full suite needs a non-placeholder OSWorld proxy configuration because 56 tasks declare
`proxy=true`, plus Google credentials because eight tasks use authenticated Drive state.

```bash
runner/setup.sh --profile current-v1
npm run build

mkdir -p results
cp validation/full-suite-contract.example.json results/full-suite-contract.json
# Set route.template_ref to the emitted name:build_id. Keep route.final=false and
# execution.execution_authorized=false while validating.

runner/run.sh \
  --contract results/full-suite-contract.json \
  --preflight-only \
  --proxy-config "$PROXY_CONFIG_FILE" \
  --vm-secret-mount "$GOOGLE_SECRET:/opt/osworld/secrets/google.json"
```

Before paid execution, set a final immutable route, resolve every endpoint label such as
`QWEN_ENDPOINT_0`, and explicitly change `execution_authorized` to `true` only for the reviewed
contract. A run can be resumed with the same command and `--run-id <existing-run-id>`.

## Public Docker parity campaign

The primary parity gate uses
`UI-MOPD/Qwen3-VL-8B-Thinking-UI-MOPD-Student` at commit
`3e6acbe78847870fc645786bfaf55c64bff84903`. The pinned public evidence has 359 evaluator outputs,
a fractional reward sum of `132.79220946530714`, and two absent tasks. Its declared-denominator
score is therefore `0.36784545558256826` over 361 tasks. The E2B campaign requires 361 valid task
results and passes the aggregate parity gate when its score is within `0.03`; it also reports the
359-task common-set comparison. This demonstrates comparable aggregate behavior, not bit-for-bit
Docker identity.

```bash
runner/setup.sh --profile ui-mopd-qwen3vl-docker
cp validation/validation-contract.example.json results/parity-contract.json

runner/run.sh \
  --contract results/parity-contract.json \
  --preflight-only \
  --proxy-config "$PROXY_CONFIG_FILE"
```

The checked-in examples are intentionally non-executable. Credentials being present never
authorize a paid E2B or model campaign.

See [Fidelity and validation](docs/FIDELITY.md), [source ownership](docs/SOURCE.md), and the
[runner guide](runner/README.md).

## Security and licensing

The guest server exposes command execution, so sandboxes use restricted ingress and the relay
authenticates upstream HTTP and WebSocket traffic with the per-sandbox traffic token. Proxy
credentials, API keys, Google credentials, dotenv files, raw run bundles, and generated checkouts
must never be committed. The repository is Apache-2.0; derived OSWorld portions are identified in
`NOTICE`.
