#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
VENV_DIR="$BACKEND_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

echo "Installing dependencies..."
source "$VENV_DIR/bin/activate"
pip install -q -r "$BACKEND_DIR/requirements.txt"

echo "Starting Call Scheduler..."
echo "Password is in $SCRIPT_DIR/.secret"
echo ""
cat "$SCRIPT_DIR/.secret" 2>/dev/null || echo "(will be generated on first run)"
echo ""

cd "$BACKEND_DIR"
python app.py
