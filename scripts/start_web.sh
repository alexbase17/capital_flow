#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PORT="${PORT:-5083}"
HOST="${HOST:-0.0.0.0}"

source "$ROOT_DIR/scripts/lib_env.sh"

unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy WS_PROXY WSS_PROXY

if [ -f ".env.local" ]; then
  set -a
  . ".env.local"
  set +a
fi

ensure_requirements

PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" -c \
  "from src.app import app, initialize_app; initialize_app(); app.run(debug=False, port=$PORT, host='$HOST')"
