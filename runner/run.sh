#!/usr/bin/env bash
# Run OSWorld; every E2B provider instance owns its own relay and sandbox.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OSWORLD_ROOT="${OSWORLD_ROOT:-$HERE/OSWorld}"

exec python3 "$HERE/campaign.py" --osworld-root "$OSWORLD_ROOT" "$@"
