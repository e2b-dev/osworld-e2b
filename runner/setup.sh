#!/usr/bin/env bash
# Self-contained OSWorld-on-E2B setup: clone OSWorld at the validated pin and
# wire in the E2B provider (realkit/provider.py + manager.py) so OSWorld's own
# run.py works with --provider_name e2b. Idempotent: re-running is safe.
#
# Usage:  ./setup.sh [--profile NAME] [dest-dir]     (default: current-v1, runner/OSWorld)
# After:  see README.md in this directory for the run steps.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
REALKIT="$HERE/../realkit"
PROFILES="$ROOT/validation/profiles.json"
PROFILE=current-v1
DEST=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        --profile)
            [ "$#" -ge 2 ] || { echo "--profile requires a value" >&2; exit 2; }
            PROFILE="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--profile NAME] [dest-dir]"
            exit 0
            ;;
        -*)
            echo "unknown option: $1" >&2
            exit 2
            ;;
        *)
            [ -z "$DEST" ] || { echo "only one destination may be supplied" >&2; exit 2; }
            DEST="$1"
            shift
            ;;
    esac
done

DEST="${DEST:-$HERE/OSWorld}"
PIN="$(python3 "$HERE/profile.py" --profiles "$PROFILES" get --name "$PROFILE" --field commit)"
UPSTREAM="$(python3 "$HERE/profile.py" --profiles "$PROFILES" get --name "$PROFILE" --field repository)"

if [ -e "$DEST" ] && [ ! -d "$DEST/.git" ]; then
    echo "destination exists but is not a Git checkout: $DEST" >&2
    exit 1
fi
if [ ! -d "$DEST/.git" ]; then
    git clone --filter=blob:none --no-checkout "$UPSTREAM" "$DEST"
fi
origin="$(git -C "$DEST" remote get-url origin)"
case "$origin" in
    "$UPSTREAM"|https://github.com/xlang-ai/OSWorld|git@github.com:xlang-ai/OSWorld.git) ;;
    *) echo "unexpected OSWorld origin: $origin" >&2; exit 1 ;;
esac
git -C "$DEST" fetch --quiet --depth=1 origin "$PIN"
git -C "$DEST" checkout --detach --quiet "$PIN"
python3 "$HERE/profile.py" --profiles "$PROFILES" verify \
    --name "$PROFILE" --checkout "$DEST" --repo-root "$ROOT"
python3 "$HERE/patch_upstream.py" "$DEST" --expected-commit "$PIN"
echo "OSWorld at $DEST (profile $PROFILE, pin $PIN)"

# ---- provider package ----------------------------------------------------
mkdir -p "$DEST/desktop_env/providers/e2b"
cp "$REALKIT/provider.py" "$REALKIT/manager.py" "$REALKIT/e2b_policy.py" "$REALKIT/ports.py" \
    "$DEST/desktop_env/providers/e2b/"
touch "$DEST/desktop_env/providers/e2b/__init__.py"

# ---- relay (runs on the host next to run.py) ------------------------------
cp "$REALKIT/relay.py" "$DEST/e2b_relay.py"
cp "$REALKIT/harness.py" "$DEST/e2b_harness.py"
cp "$REALKIT/e2b_policy.py" "$DEST/e2b_policy.py"

echo
echo "Done. Next (see README.md):"
echo "  1. pip install -r $DEST/requirements.txt -r $HERE/requirements-e2b.txt"
echo "  2. export E2B_API_KEY=..."
echo "  3. $HERE/run.sh --observation_type screenshot --model <model> --test_all_meta_path ..."
