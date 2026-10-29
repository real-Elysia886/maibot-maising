#!/usr/bin/env bash
# AI Singing Inference Server Linux Startup Script
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export PYTHONNOUSERSITE=1

echo "========================================================"
echo "       AI Singing Inference Backend Server (Linux)"
echo "========================================================"
echo ""

PYTHON_BIN="${SING_PYTHON:-python3}"
if [ -z "${SING_PYTHON:-}" ] && [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
elif [ -z "${SING_PYTHON:-}" ] && [ -n "${VIRTUAL_ENV:-}" ]; then
    PYTHON_BIN="$VIRTUAL_ENV/bin/python"
fi

echo "[Info] Using Python: $PYTHON_BIN"
echo "[Info] Starting sing_server.py (see settings.json for host and port) ..."
echo ""

exec "$PYTHON_BIN" -s sing_server.py
