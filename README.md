# OSWorld on E2B

This repository reconstructs OSWorld's Ubuntu desktop as an E2B Template and provides the provider,
relay, runner, and validation contracts needed to execute the pinned OSWorld benchmark. It is a
native port: it does not run OSWorld's qcow2 image or a nested hypervisor.

The implementation targets OSWorld commit `7a17d3abc86d524420ea4ec96752f84d245fea74`.
`upstream.lock.json` is the machine-readable source lock. The checkout is fetched into the ignored
`runner/OSWorld/` directory; no benchmark dataset or vendored repository is committed here.

## Architecture

- `template/` builds an Ubuntu 22.04 GNOME desktop and installs OSWorld's guest-control surface.
- `realkit/` owns restricted-ingress E2B lifecycle, authenticated HTTP/WebSocket relay, fresh-task
  replacement, and named runtime snapshots.
- `runner/` fetches and patches the exact OSWorld revision, runs OSWorld, and performs smoke or
  environment-path validation.
- `validation/` selects a fixed cross-application task sample without embedding task contents.

Every launch path requires an immutable `name:build_id` Template reference. A mutable Template name
is rejected before sandbox creation.

## Build identity

`template/inputs.lock.json` pins the OSWorld commit and the Ubuntu base image by platform-specific
digest. The guest Python environment is a complete transitive lock with artifact hashes, and npm
uses `package-lock.json`. The build command hashes those inputs, the Template sources, all copied
guest files, and the CPU and memory allocation into a deterministic recipe digest. It derives the
Template name `osworld-gnome-<digest-prefix>` from that digest; callers cannot supply a mutable
name.

The recipe is not byte-reproducible. Ubuntu packages, Google Chrome stable, and the VS Code Debian
download are resolved during the build as documented in `template/inputs.lock.json`. Each build
records the recipe digest, per-input digests, unresolved inputs, and E2B build ID in the ignored
`results/template-build.json` receipt. The guest also records the resolved Debian package inventory.
Only the receipt's `name:build_id` is an immutable runnable artifact identity; a matching recipe
digest alone does not identify identical output bytes.

## Local checks

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
```

The guest build and live validation require an E2B account and are deliberately separate from the
offline checks:

```bash
cp .env.example .env.local
export E2B_API_KEY='...'
npm run build
export GUEST_TEMPLATE='osworld-gnome-<recipe-digest-prefix>:<build-id-from-build-output>'

runner/setup.sh
uv run --with-requirements runner/OSWorld/requirements.txt \
  --with-requirements runner/requirements-e2b.txt runner/validate.sh
```

Build receipts and validation output are written beneath ignored generated-output directories.
`PATH_PASS` means reset, setup, observation, action, and evaluator transport completed. It is not a
benchmark task pass and must not be reported as one.

See [Fidelity and validation](docs/FIDELITY.md) for the compatibility boundary and
[runner/README.md](runner/README.md) for operator commands.

## Security and licensing

The guest server exposes command execution, so the relay disables public traffic and authenticates
each proxied request with the sandbox traffic token. Never commit credentials, dotenv files,
vendored OSWorld checkouts, generated results, or raw trajectories. Report vulnerabilities through
the process in [SECURITY.md](SECURITY.md).

The repository is Apache-2.0. Portions derived from OSWorld are identified in [NOTICE](NOTICE).
