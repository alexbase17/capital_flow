#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

source "$ROOT_DIR/scripts/lib_env.sh"
ensure_requirements

echo "== Python unit tests =="
"$PYTHON_BIN" -W error::ResourceWarning -m unittest discover -s tests

echo "== Python compile check =="
"$PYTHON_BIN" -m compileall scripts src tests

echo "== Taxonomy data validation =="
"$PYTHON_BIN" scripts/validate_taxonomy_data.py

echo "== JavaScript syntax check =="
for script in src/static/capital_flow*.js; do
  node --check "$script"
done
node --check scripts/verify_dashboard_browser.mjs

echo "== Git whitespace check =="
git diff --check

echo "All verification steps passed."
