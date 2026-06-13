#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

source "$ROOT_DIR/scripts/lib_env.sh"
ensure_python

unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
export no_proxy="127.0.0.1,localhost,0.0.0.0"
export NO_PROXY="$no_proxy"

CHECK_HOST="${CHECK_HOST:-127.0.0.1}"
PORT="${PORT:-5083}"
if [ -n "${BASE_URL:-}" ]; then
  BASE_URL_CANDIDATES=("$BASE_URL")
else
  BASE_URL_CANDIDATES=("http://$CHECK_HOST:$PORT")
  if [ "$CHECK_HOST" = "127.0.0.1" ]; then
    BASE_URL_CANDIDATES+=("http://0.0.0.0:$PORT")
  fi
fi

try_url() {
  local url="$1"
  local output_file="$2"
  "$PYTHON_BIN" - "$url" "$output_file" <<'PY'
import sys
import time
import urllib.error
import urllib.request

url, output_file = sys.argv[1], sys.argv[2]
started = time.monotonic()
request = urllib.request.Request(url, headers={"User-Agent": "capital-flow-check/1.0"})
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    with opener.open(request, timeout=30) as response:
        status = response.status
        body = response.read()
except urllib.error.HTTPError as error:
    status = error.code
    body = error.read()
except urllib.error.URLError as error:
    elapsed = time.monotonic() - started
    reason = getattr(error, "reason", error)
    print(f"request failed after {elapsed:.6f}s: {reason}", file=sys.stderr)
    raise SystemExit(2)
elapsed = time.monotonic() - started
with open(output_file, "wb") as fh:
    fh.write(body)
print(f"{status} {elapsed:.6f}")
PY
}

select_base_url() {
  local base_url result status attempt
  for base_url in "${BASE_URL_CANDIDATES[@]}"; do
    for attempt in $(seq 1 10); do
      if result="$(try_url "$base_url/" "/tmp/capital_flow_home.html")"; then
        status="${result%% *}"
        if [ "$status" = "200" ]; then
          ACTIVE_BASE_URL="$base_url"
          echo "/ -> ${result#"$status "}s via $ACTIVE_BASE_URL"
          return
        fi
      fi
      sleep 1
    done
  done
  echo "No reachable capital-flow service found. Tried: ${BASE_URL_CANDIDATES[*]}" >&2
  exit 1
}

check_endpoint() {
  local path="$1"
  local output_file="$2"
  local result status elapsed attempt
  result=""
  for attempt in $(seq 1 10); do
    if result="$(try_url "$ACTIVE_BASE_URL$path" "$output_file")"; then
      break
    fi
    if [ "$attempt" = "10" ]; then
      echo "Failed to connect to $ACTIVE_BASE_URL$path after $attempt attempts" >&2
      exit 1
    fi
    sleep 1
  done
  status="${result%% *}"
  elapsed="${result#* }"
  echo "$path -> $status ${elapsed}s"
  if [ "$status" != "200" ]; then
    echo "Unexpected HTTP status for $path; response saved to $output_file" >&2
    exit 1
  fi
}

select_base_url
check_endpoint "/api/capital-flow" "/tmp/capital_flow_api.json"

if [ "${CHECK_AI_SUMMARY:-0}" = "1" ]; then
  check_endpoint "/api/capital-flow/ai-summary" "/tmp/capital_flow_ai_summary.json"
fi

echo "Web checks passed for $ACTIVE_BASE_URL"
