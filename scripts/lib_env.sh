#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
REQUIREMENTS_FILE="$ROOT_DIR/requirements.txt"
REQUIREMENTS_STAMP="$VENV_DIR/.requirements.sha256"

export PYTHONDONTWRITEBYTECODE="${PYTHONDONTWRITEBYTECODE:-1}"
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-/tmp/capital_flow_pycache}"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-/tmp/capital_flow_pip_cache}"

python_works() {
  local python_bin="$1"
  [ -x "$python_bin" ] && "$python_bin" -c "import sys; raise SystemExit(0)" >/dev/null 2>&1
}

ensure_python() {
  if [ -n "${PYTHON_BIN:-}" ]; then
    if python_works "$PYTHON_BIN"; then
      export PYTHON_BIN
      return
    fi
    echo "Configured PYTHON_BIN is not usable: $PYTHON_BIN" >&2
    exit 1
  fi

  PYTHON_BIN="$VENV_DIR/bin/python"
  if ! python_works "$PYTHON_BIN"; then
    echo "Rebuilding Python virtualenv at $VENV_DIR"
    python3 -m venv --clear "$VENV_DIR"
  fi
  if ! python_works "$PYTHON_BIN"; then
    echo "Python virtualenv is still not usable at $PYTHON_BIN" >&2
    exit 1
  fi
  export PYTHON_BIN
}

requirements_hash() {
  shasum -a 256 "$REQUIREMENTS_FILE" | awk '{print $1}'
}

ensure_requirements() {
  ensure_python
  local current_hash
  current_hash="$(requirements_hash)"
  if [ ! -f "$REQUIREMENTS_STAMP" ] || [ "$(cat "$REQUIREMENTS_STAMP")" != "$current_hash" ]; then
    echo "Installing Python requirements"
    "$PYTHON_BIN" -m pip install -r "$REQUIREMENTS_FILE"
    echo "$current_hash" > "$REQUIREMENTS_STAMP"
  else
    echo "Python requirements unchanged; skipping install"
  fi
}
