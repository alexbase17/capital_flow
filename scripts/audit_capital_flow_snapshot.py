#!/usr/bin/env python3
"""Audit current capital-flow payload for suspicious data-quality signals."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from src.capital_flow.fetcher import cache_file_path, read_cache  # noqa: E402


DEFAULT_WINDOWS = ("1d", "5d", "20d", "60d")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", default="1d", help="Payload cache window key to audit")
    parser.add_argument("--max-items", type=int, default=12, help="Maximum suspicious rows to print")
    parser.add_argument("--fail-on-warning", action="store_true", help="Exit non-zero when warnings are found")
    args = parser.parse_args()

    payload = load_payload(args.window)
    audit = audit_payload(payload, max_items=args.max_items)
    print(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if args.fail_on_warning and audit["warning_count"] else 0


def load_payload(window_key: str) -> dict[str, Any]:
    payload = read_cache(cache_file_path(f"capital_flow_payload/{window_key}"), max_age_seconds=None)
    if not isinstance(payload, dict):
        raise SystemExit(f"No cached capital-flow payload found for window {window_key!r}")
    return payload


def audit_payload(payload: dict[str, Any], *, max_items: int) -> dict[str, Any]:
    warnings = []
    suspicious_rows = []
    etf = payload.get("etf") or {}
    quality = etf.get("quality") or {}
    coverage = etf.get("coverage") or {}
    data_status = etf.get("data_status") or {}

    if data_status.get("payload_cache_status") == "stale":
        warnings.append("payload is using stale cache")
    if number(quality.get("nav_estimate_ratio_pct")) > 5:
        warnings.append("NAV estimate ratio is above 5%")
    if number(quality.get("skipped_flow_count")) > 0:
        warnings.append("some ETF daily flow points were skipped")
    if coverage.get("target_coverage_pct") is not None and number(coverage.get("target_coverage_pct")) < 80:
        warnings.append("frontend target ETF taxonomy coverage is below 80%")

    for item in iter_window_rows(payload):
        flow_yi = number(item.get("flow_yi"))
        scale_yi = number(item.get("scale_yi"))
        ratio_pct = number(item.get("flow_ratio_pct"))
        turnover_pct = number(item.get("turnover_avg_pct"))
        if abs(flow_yi) >= 100 or abs(ratio_pct) >= 35 or turnover_pct >= 30:
            suspicious_rows.append(item)
        elif scale_yi > 0 and abs(flow_yi) / scale_yi >= 0.35:
            suspicious_rows.append(item)

    suspicious_rows = sorted(
        suspicious_rows,
        key=lambda row: max(abs(number(row.get("flow_yi"))), abs(number(row.get("flow_ratio_pct"))) * 2),
        reverse=True,
    )[:max_items]
    if suspicious_rows:
        warnings.append("suspicious high-magnitude flow or turnover rows found")

    return {
        "as_of_date": etf.get("latest_date"),
        "payload_schema_version": payload.get("payload_schema_version"),
        "warning_count": len(warnings),
        "warnings": warnings,
        "quality": {
            "nav_estimate_ratio_pct": quality.get("nav_estimate_ratio_pct"),
            "skipped_flow_count": quality.get("skipped_flow_count"),
            "split_adjusted_count": quality.get("split_adjusted_count"),
            "target_coverage_pct": coverage.get("target_coverage_pct"),
            "payload_cache_status": data_status.get("payload_cache_status"),
        },
        "suspicious_rows": suspicious_rows,
    }


def iter_window_rows(payload: dict[str, Any]):
    for window_key in DEFAULT_WINDOWS:
        sections = payload.get("window_payloads", {}).get(window_key, {}).get("etf", {}).get("sections", {})
        for section_key, section in sections.items():
            for row in section.get("rows") or []:
                yield {
                    "window": window_key,
                    "section": section_key,
                    "name": row.get("display_name") or row.get("index_name"),
                    "flow_yi": row.get("net_flow_yi"),
                    "flow_ratio_pct": row.get("net_flow_ratio"),
                    "turnover_avg_pct": row.get("turnover_ratio"),
                    "scale_yi": row.get("scale_yi"),
                }


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    raise SystemExit(main())
