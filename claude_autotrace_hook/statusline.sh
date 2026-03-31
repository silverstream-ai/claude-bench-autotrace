#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="${SCRIPT_DIR}/../venv/bin/python3"

if [[ -x "$VENV_PYTHON" ]]; then
    exec "$VENV_PYTHON" "$SCRIPT_DIR/statusline.py"
fi
