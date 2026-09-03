# Run OSWorld with E2B

## Prepare a pinned checkout

```bash
runner/setup.sh --profile current-v1
uv sync --locked --all-groups
uv pip install -r runner/OSWorld/requirements.txt -r runner/requirements-e2b.txt
```

`current-v1` is the default and contains `all` (369), `nogdrive` (361), and `gdrive` (8). Use
`--profile ui-mopd-qwen3vl-docker` for the historical public Docker comparison. Setup fetches the
exact commit, verifies its origin and generated inventory, rejects unrelated checkout changes, and
applies the same E2B boundary patch deterministically.

Build the Template and retain the immutable reference printed by the build:

```bash
export E2B_API_KEY='...'
npm run build
```

Only `name:build_id` is accepted by the run contract. Mutable template names are rejected before
any sandbox is created.

## Run preflight

The examples intentionally contain `route.final: false` and `execution_authorized: false`.

```bash
mkdir -p results
cp validation/full-suite-contract.example.json results/full-suite-contract.json

runner/run.sh \
  --contract results/full-suite-contract.json \
  --preflight-only \
  --proxy-config "$PROXY_CONFIG_FILE" \
  --vm-secret-mount "$GOOGLE_SECRET:/opt/osworld/secrets/google.json"
```

For the 361-task public comparison, use `validation/validation-contract.example.json` and omit the
Google mount. A proxy remains required because 45 tasks in that historical inventory declare
`proxy=true`.

Preflight checks source and inventory identities, runner and model settings, immutable route
syntax, proxy capability, secret mount constraints, timeout/retry limits, sandbox concurrency, and
the independent worst-case model request cap. It performs no paid E2B or model work.

## Authorize and execute

Create an operator-owned contract under ignored `results/`, set its template to the emitted
`name:build_id`, set `route.final: true`, and define every endpoint label in the environment. Review
the task count and both caps, then set `execution_authorized: true` only when that exact paid run is
authorized.

```bash
export QWEN_ENDPOINT_0='http://model-host-0.example/v1'

runner/run.sh \
  --contract results/parity-contract.json \
  --proxy-config "$PROXY_CONFIG_FILE" \
  --num-envs 8 \
  --run-id qwen-e2b-parity
```

To resume, repeat the command with the same contract and `--run-id`. Identity drift is rejected.
Tasks already holding valid terminal results are skipped; invalid and crash-visible attempts retry
only within the contract limit.

Each task process owns a relay with a unique dynamic port bundle and one sandbox. Result paths,
logs, relay events, and traffic tokens are private to that attempt, so task-level parallelism is the
default. The sandbox cap controls simultaneous environments. Endpoint labels are assigned
round-robin and the model request cap remains independent because model-serving capacity may be
shared even though sandboxes are not.

Every scheduled attempt is represented in `results/runs/<run-id>/attempts.jsonl`. Per-attempt
directories retain all produced upstream artifacts and checksum catalogs. `aggregate.json` is
updated atomically and separates valid zeros from infrastructure-invalid outcomes.

## Environment-path smoke validation

```bash
export GUEST_TEMPLATE='osworld-gnome-<digest>:<build-id>'
runner/validate.sh
```

This runs the named 24-task smoke manifest twice. `PATH_PASS` means reset, setup, observation,
action, and evaluator transport worked; it is not a benchmark task pass.

Useful relay settings are `SANDBOX_TIMEOUT_S` (default 3600), `RELAY_HTTP_TIMEOUT_S` (default 240),
and `GUEST_READY_TIMEOUT_S` (default 180). The headless adapter reports VNC port 0 because OSWorld
uses the relay's HTTP, CDP, and VLC endpoints instead.
