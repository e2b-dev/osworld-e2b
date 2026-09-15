#!/usr/bin/env bash
# Audit the locked host environment and both runtime dependency locks.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AUDIT_TMP="$(mktemp -d "${TMPDIR:-/tmp}/osworld-e2b-audit.XXXXXX")"
cleanup() {
    case "$AUDIT_TMP" in
        "${TMPDIR:-/tmp}"/osworld-e2b-audit.*) rm -rf -- "$AUDIT_TMP" ;;
        *) echo "refusing to remove unexpected audit path: $AUDIT_TMP" >&2 ;;
    esac
}
trap cleanup EXIT INT TERM

cd "$ROOT"
uv export --quiet --locked --all-groups --no-emit-project --no-hashes \
    --output-file "$AUDIT_TMP/host-requirements.txt"

for requirements in \
    "$AUDIT_TMP/host-requirements.txt" \
    runner/requirements-e2b.txt
do
    uv run --with pip-audit==2.10.1 pip-audit \
        --requirement "$requirements" \
        --desc=off \
        --progress-spinner=off
done

# Audit the guest's exact direct pins without host-platform resolution.
uv run --with pip-audit==2.10.1 pip-audit \
    --requirement template/files/server/requirements.txt \
    --no-deps \
    --disable-pip \
    --desc=off \
    --progress-spinner=off
# Then audit the complete Linux/amd64 transitive lock directly.
uv run --with pip-audit==2.10.1 pip-audit \
    --requirement template/files/server/requirements.lock \
    --disable-pip \
    --desc=off \
    --progress-spinner=off
