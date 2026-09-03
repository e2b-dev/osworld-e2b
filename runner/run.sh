#!/usr/bin/env bash
# Run OSWorld; every E2B provider instance owns its own relay and sandbox.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OSWORLD_ROOT="${OSWORLD_ROOT:-$HERE/OSWorld}"
UPSTREAM_RUNNER="${OSWORLD_RUNNER:-scripts/python/run_multienv.py}"

if [[ ! "${GUEST_TEMPLATE:-}" =~ ^[a-z0-9][a-z0-9_-]*:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
    echo "GUEST_TEMPLATE must be an immutable name:build_id reference" >&2
    exit 2
fi
export GUEST_TEMPLATE

cd "$OSWORLD_ROOT"
python3 "$UPSTREAM_RUNNER" \
    --provider_name e2b \
    --path_to_vm "$GUEST_TEMPLATE" \
    --headless \
    "$@"
