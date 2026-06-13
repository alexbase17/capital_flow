"""API payload contract checks for the capital-flow dashboard."""

from __future__ import annotations

from typing import Any


REQUIRED_TOP_LEVEL_KEYS = {
    "data_status",
    "north_south",
    "etf",
    "windows",
    "default_window",
    "selected_window",
    "selected_window_label",
    "window_payloads",
    "threshold_yi",
    "notes",
    "ai_summary",
}
REQUIRED_ETF_KEYS = {
    "latest_date",
    "previous_date",
    "nav_date",
    "data_status",
    "coverage",
    "quality",
    "sections",
}
REQUIRED_SECTION_KEYS = {"title", "rows"}
REQUIRED_ROW_KEYS = {
    "index_name",
    "display_name",
    "index_code",
    "change_pct",
    "net_flow_yi",
    "net_flow_ratio",
    "turnover_yi",
    "turnover_ratio",
    "scale_yi",
    "start_scale_yi",
    "etf_count",
    "nav_count",
    "close_estimate_count",
    "skipped_flow_count",
    "split_adjusted_count",
    "price_source_label",
    "daily_net_flow",
    "daily_change_pct",
    "daily_turnover",
    "scale_audit",
    "top_etfs",
    "debug_etfs",
}
EXPECTED_SECTIONS = {"broad", "strategy", "a_industry", "hk_industry"}


def validate_capital_flow_payload(payload: dict[str, Any]) -> dict[str, Any]:
    missing = REQUIRED_TOP_LEVEL_KEYS - payload.keys()
    if missing:
        raise ValueError(f"capital-flow payload missing keys: {sorted(missing)}")
    _expect_dict(payload["north_south"], "north_south")
    _expect_dict(payload["data_status"], "data_status")
    etf = _expect_dict(payload["etf"], "etf")
    etf_missing = REQUIRED_ETF_KEYS - etf.keys()
    if etf_missing:
        raise ValueError(f"capital-flow etf payload missing keys: {sorted(etf_missing)}")
    sections = _expect_dict(etf["sections"], "etf.sections")
    section_missing = EXPECTED_SECTIONS - sections.keys()
    if section_missing:
        raise ValueError(f"capital-flow sections missing keys: {sorted(section_missing)}")
    for section_name, section in sections.items():
        _validate_section(section_name, _expect_dict(section, f"etf.sections.{section_name}"))
    _expect_dict(etf["coverage"], "etf.coverage")
    _expect_dict(etf["quality"], "etf.quality")
    _expect_dict(etf["data_status"], "etf.data_status")
    _expect_dict(payload["windows"], "windows")
    window_payloads = _expect_dict(payload["window_payloads"], "window_payloads")
    for window_key, window_payload in window_payloads.items():
        window_dict = _expect_dict(window_payload, f"window_payloads.{window_key}")
        _expect_dict(window_dict.get("north_south"), f"window_payloads.{window_key}.north_south")
        window_etf = _expect_dict(window_dict.get("etf"), f"window_payloads.{window_key}.etf")
        _expect_dict(window_etf.get("data_status"), f"window_payloads.{window_key}.etf.data_status")
        window_sections = _expect_dict(window_etf.get("sections"), f"window_payloads.{window_key}.etf.sections")
        section_missing = EXPECTED_SECTIONS - window_sections.keys()
        if section_missing:
            raise ValueError(f"capital-flow window {window_key} sections missing keys: {sorted(section_missing)}")
        for section_name, section in window_sections.items():
            _validate_section(
                f"{window_key}.{section_name}",
                _expect_dict(section, f"window_payloads.{window_key}.etf.sections.{section_name}"),
            )
    if not isinstance(payload["notes"], list):
        raise ValueError("capital-flow notes must be a list")
    _validate_ai_summary(_expect_dict(payload["ai_summary"], "ai_summary"))
    return payload


def _validate_section(section_name: str, section: dict[str, Any]) -> None:
    missing = REQUIRED_SECTION_KEYS - section.keys()
    if missing:
        raise ValueError(f"capital-flow section {section_name} missing keys: {sorted(missing)}")
    rows = section["rows"]
    if not isinstance(rows, list):
        raise ValueError(f"capital-flow section {section_name} rows must be a list")
    for index, row in enumerate(rows):
        row_dict = _expect_dict(row, f"etf.sections.{section_name}.rows[{index}]")
        missing_row_keys = REQUIRED_ROW_KEYS - row_dict.keys()
        if missing_row_keys:
            raise ValueError(
                f"capital-flow section {section_name} row {index} missing keys: {sorted(missing_row_keys)}"
            )


def _expect_dict(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"capital-flow {path} must be a dict")
    return value


def _validate_ai_summary(summary: dict[str, Any]) -> None:
    for key in ("status", "source", "headline", "focus_items", "risks", "data_quality"):
        if key not in summary:
            raise ValueError(f"capital-flow ai_summary missing key: {key}")
    if not isinstance(summary["focus_items"], list):
        raise ValueError("capital-flow ai_summary.focus_items must be a list")
    if not isinstance(summary["risks"], list):
        raise ValueError("capital-flow ai_summary.risks must be a list")
