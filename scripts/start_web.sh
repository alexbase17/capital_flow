#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PORT="${PORT:-5083}"
HOST="${HOST:-0.0.0.0}"
VENV_DIR="${VENV_DIR:-.venv}"

unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy WS_PROXY WSS_PROXY

if [ -f ".env.local" ]; then
  set -a
  . ".env.local"
  set +a
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
  python3 -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install -r requirements.txt

PYTHONDONTWRITEBYTECODE=1 "$VENV_DIR/bin/python" -c \
  "from src.app import app, initialize_app; initialize_app(); app.run(debug=False, port=$PORT, host='$HOST')"
