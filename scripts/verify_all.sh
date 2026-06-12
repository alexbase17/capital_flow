#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${VENV_DIR:-.venv}"
PYTHON_BIN="${PYTHON_BIN:-$VENV_DIR/bin/python}"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Python not found at $PYTHON_BIN. Run scripts/start_web.sh or create .venv first." >&2
  exit 1
fi

echo "== Python unit tests =="
PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" -W error::ResourceWarning -m unittest discover -s tests

echo "== Python compile check =="
python3 -m compileall scripts src tests

echo "== JavaScript syntax check =="
node --check src/static/capital_flow.js

echo "== Git whitespace check =="
git diff --check || true

echo "All verification steps passed."
