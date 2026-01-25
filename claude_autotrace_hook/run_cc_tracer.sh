#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${CLAUDE_PROJECT_DIR}/venv"
VENV_PYTHON="${VENV_DIR}/bin/python3"

# Check if CLAUDE_PROJECT_DIR is set
if [[ -z "${CLAUDE_PROJECT_DIR}" ]]; then
    echo '{"status":"error","message":"CLAUDE_PROJECT_DIR environment variable is not set. This hook requires Claude Code to set the project directory."}'
    exit 0
fi

# Check if venv directory exists
if [[ ! -d "${VENV_DIR}" ]]; then
    echo '{"status":"error","message":"Python venv not found at '"${VENV_DIR}"'. Create it with: python3 -m venv venv && venv/bin/pip install -r requirements.txt"}'
    exit 0
fi

# Check if python3 is executable in the venv
if [[ ! -x "${VENV_PYTHON}" ]]; then
    echo '{"status":"error","message":"Python executable not found at '"${VENV_PYTHON}"'. The venv may be corrupted. Recreate it with: rm -rf venv && python3 -m venv venv && venv/bin/pip install -r requirements.txt"}'
    exit 0
fi

# Quick check that required packages are installed
if ! "${VENV_PYTHON}" -c "import pydantic_settings, opentelemetry" 2>/dev/null; then
    echo '{"status":"error","message":"Required Python packages not installed in venv. Run: venv/bin/pip install -r requirements.txt"}'
    exit 0
fi

# Run the tracer
exec "${VENV_PYTHON}" "$SCRIPT_DIR/cc_tracer.py"
