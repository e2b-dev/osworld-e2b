#!/usr/bin/env bash
# Run the fixed no-agent environment-path manifest twice and preserve evidence.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
OSWORLD_ROOT="${OSWORLD_ROOT:-$HERE/OSWorld}"
MANIFEST="${VALIDATION_MANIFEST:-$ROOT/validation/manifest.json}"
RESULTS_DIR="${RESULTS_DIR:-$ROOT/results}"
RUNS="${VALIDATION_RUNS:-2}"
if [[ ! "${GUEST_TEMPLATE:-}" =~ :[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; then
    echo "GUEST_TEMPLATE must be an immutable name:build_id reference from npm run build" >&2
    exit 2
fi
mkdir -p "$RESULTS_DIR"

overall=0
relay_pid=""
cleanup_current() {
    curl -fsS -X POST http://127.0.0.1:14999/stop >/dev/null 2>&1 || true
    if [ -n "$relay_pid" ]; then wait "$relay_pid" 2>/dev/null || true; fi
    relay_pid=""
}
trap cleanup_current EXIT INT TERM
for run_number in $(seq 1 "$RUNS"); do
    stamp="$(date -u +%Y%m%dT%H%M%SZ)-run${run_number}"
    relay_log="$RESULTS_DIR/$stamp-relay.log"
    output="$RESULTS_DIR/$stamp.json"
    python3 "$OSWORLD_ROOT/e2b_relay.py" 2>"$relay_log" &
    relay_pid=$!
    ready=0
    for _ in $(seq 1 120); do
        if curl -fsS http://127.0.0.1:14999/health >/dev/null 2>&1; then ready=1; break; fi
        if ! kill -0 "$relay_pid" 2>/dev/null; then break; fi
        sleep 2
    done
    if [ "$ready" -ne 1 ]; then
        tail -100 "$relay_log" >&2
        cleanup_current
        overall=1
        continue
    fi

    # OSWorld has a few import-time and evaluator-time paths relative to its
    # repository (for example evaluation_examples/settings/proxy). Run the
    # harness from the pinned checkout so those upstream paths resolve.
    (
        cd "$OSWORLD_ROOT" || exit
        python3 "$OSWORLD_ROOT/e2b_harness.py" \
            --osworld-root "$OSWORLD_ROOT" \
            --manifest "$MANIFEST" \
            --output "$output"
    )
    status=$?
    [ "$status" -eq 0 ] || overall=1
    cleanup_current
done
exit "$overall"
