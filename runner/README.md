# Run OSWorld with the E2B provider

The relay creates a restricted-ingress E2B sandbox, proxies OSWorld's HTTP and
Chrome WebSocket traffic, and replaces the sandbox on every snapshot revert.
The traffic token stays in the relay process and is never passed to OSWorld.

## Setup

```bash
runner/setup.sh
uv sync --locked --all-groups
uv pip install -r runner/OSWorld/requirements.txt -r runner/requirements-e2b.txt
```

`setup.sh` fetches the exact commit in `upstream.lock.json`, verifies its Git
identity and origin, rejects unrelated checkout changes, and applies the same
adapter patch deterministically on every run.

Build the template from the repository root and use the immutable build
reference printed by the build command:

```bash
export E2B_API_KEY='...'
npm run build
export GUEST_TEMPLATE='osworld-gnome-<recipe-digest-prefix>:<build-id>'
```

The manager, relay, validation script, and normal run script reject a missing
or mutable `GUEST_TEMPLATE` before a sandbox is created.

## Fixed environment-path validation

```bash
./validate.sh
```

This runs `validation/manifest.json` twice. Output JSON, JSONL, and relay logs
are written to `results/`. `PATH_PASS` means OSWorld's setup, observation,
action, and evaluator paths completed; it is not task success.

## Agent run

Pass normal OSWorld arguments after `run.sh`:

```bash
./run.sh \
  --observation_type screenshot \
  --model <model> \
  --test_all_meta_path evaluation_examples/test_small.json \
  --client_password password
```

## Mid-run snapshots

OSWorld's `save_state(snapshot_name)` maps to an E2B snapshot of the running
guest — memory and filesystem are captured, the sandbox pauses for a few
seconds and resumes. A later `revert_to_snapshot` with the same name creates a
fresh sandbox in that exact state; one snapshot can seed any number of
sandboxes. Names that were never saved (including OSWorld's default
`init_state`) revert to the template base state instead. To verify live
against a running relay:

```bash
python3 snapshot_probe.py
```

Useful settings:

- `SANDBOX_TIMEOUT_S` controls the E2B sandbox lifetime in seconds (default
  3600; account-tier limits still apply).
- `RELAY_HTTP_TIMEOUT_S` controls one proxied HTTP request (default 240).
- `GUEST_READY_TIMEOUT_S` controls guest readiness waiting (default 180).

The adapter runs headless and returns 0 for OSWorld's VNC port. One relay
process supports one OSWorld environment; parallel runs need separate port
namespaces or one relay process per isolated host/container.
