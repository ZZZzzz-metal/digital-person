#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 2 ]; then
    echo 'Usage: start.sh TEST_FILE RESULT_DIR' >&2
    exit 2
fi
# The name comes from the original official launcher; B6 verifies this in Linux.
source activate conda_env
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1
export PYTHONDONTWRITEBYTECODE=1
if [ -d "$SCRIPT_DIR/src" ]; then
    export PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
fi
exec "${PYTHON_BIN:-python3}" "$SCRIPT_DIR/run_inference.py" "$1" "$2"
