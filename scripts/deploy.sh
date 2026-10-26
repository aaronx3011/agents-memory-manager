#!/usr/bin/env bash
# Match the coordinator's invocation, with fail-closed explicit environment/release selection.
set -euo pipefail
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$BASE_DIR/scripts/deploy.py" "$@"
