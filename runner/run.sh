#!/usr/bin/env bash
# Run OSWorld with one secure E2B guest at a time and fresh-sandbox task resets.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OSWORLD_ROOT="${OSWORLD_ROOT:-$HERE/OSWorld}"
LOG="${E2B_RELAY_LOG:-$OSWORLD_ROOT/e2b-relay.log}"

if [[ ! "${GUEST_TEMPLATE:-}" =~ ^[a-z0-9][a-z0-9_-]*:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
    echo "GUEST_TEMPLATE must be an immutable name:build_id reference" >&2
    exit 2
fi
export GUEST_TEMPLATE

python3 "$OSWORLD_ROOT/e2b_relay.py" 2>"$LOG" &
relay_pid=$!
cleanup() {
    curl -fsS -X POST http://127.0.0.1:14999/stop >/dev/null 2>&1 || true
    wait "$relay_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 120); do
    curl -fsS http://127.0.0.1:14999/health >/dev/null 2>&1 && break
    kill -0 "$relay_pid" 2>/dev/null || { tail -100 "$LOG" >&2; exit 1; }
    sleep 2
done
curl -fsS http://127.0.0.1:14999/health >/dev/null

cd "$OSWORLD_ROOT"
python3 run.py \
    --provider_name e2b \
    --path_to_vm "$GUEST_TEMPLATE" \
    --headless \
    "$@"
