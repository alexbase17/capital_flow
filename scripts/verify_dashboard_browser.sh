#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BASE_URL="${BASE_URL:-http://127.0.0.1:5083}"

BASE_URL="$BASE_URL" scripts/check_web.sh
BASE_URL="$BASE_URL" node scripts/verify_dashboard_browser.mjs "$BASE_URL"
