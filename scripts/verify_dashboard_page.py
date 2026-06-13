#!/usr/bin/env python3
"""Smoke-test the capital-flow dashboard HTML, static assets, and API."""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request


BASE_URL = "http://127.0.0.1:5083"
REQUIRED_SCRIPTS = (
    "capital_flow_state.js",
    "capital_flow_format.js",
    "capital_flow_data.js",
    "capital_flow_charts.js",
    "capital_flow_table.js",
    "capital_flow.js",
)


def main() -> int:
    base_url = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else BASE_URL
    html = request_text(f"{base_url}/")
    script_urls = re.findall(r'<script src="([^"]+)"></script>', html)
    script_names = [url.split("/static/", 1)[-1].split("?", 1)[0] for url in script_urls]
    errors = []
    for script_name in REQUIRED_SCRIPTS:
        if script_name not in script_names:
            errors.append(f"missing script in HTML: {script_name}")
    if script_names[-len(REQUIRED_SCRIPTS) :] != list(REQUIRED_SCRIPTS):
        errors.append(f"unexpected script order: {script_names}")

    script_texts = {}
    for script_url in script_urls:
        script_name = script_url.split("/static/", 1)[-1].split("?", 1)[0]
        if script_name.startswith("capital_flow"):
            script_texts[script_name] = request_text(f"{base_url}{script_url}")
    entry_script = script_texts.get("capital_flow.js", "")
    if entry_script.count("loadCapitalFlow();") != 1:
        errors.append("capital_flow.js must call loadCapitalFlow exactly once")
    if "DOMContentLoaded" not in entry_script:
        errors.append("capital_flow.js must initialize after DOMContentLoaded when needed")

    payload = json.loads(request_text(f"{base_url}/api/capital-flow"))
    if not isinstance(payload.get("window_payloads"), dict):
        errors.append("API payload missing window_payloads")
    if not payload.get("etf", {}).get("sections"):
        errors.append("API payload missing ETF sections")

    if errors:
        for error in errors:
            print(f"dashboard smoke failed: {error}", file=sys.stderr)
        return 1
    print(f"Dashboard smoke passed for {base_url}")
    return 0


def request_text(url: str) -> str:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, headers={"User-Agent": "capital-flow-dashboard-smoke/1.0"})
    try:
        with opener.open(request, timeout=30) as response:
            if response.status != 200:
                raise RuntimeError(f"{url} returned HTTP {response.status}")
            return response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"failed to request {url}: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
