#!/usr/bin/env bash
set -e

PORT="${PORT:-5000}"
PID=$(lsof -ti :"$PORT" 2>/dev/null || true)
if [ -n "$PID" ]; then
  echo "Killing existing process on port $PORT (PID: $PID)..."
  kill $PID 2>/dev/null || true
  sleep 1
fi

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

echo "Starting Call Scheduler on port $PORT..."
echo ""

cd "$BACKEND_DIR"
python app.py
