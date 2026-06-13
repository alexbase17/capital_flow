"""Signal extraction for capital-flow AI summaries."""

from __future__ import annotations

from typing import Any


WINDOW_KEYS = ("1d", "5d", "20d", "60d")
SECTION_LABELS = {
    "broad": "宽基",
    "a_industry": "A股行业",
    "hk_industry": "港股行业",
    "strategy": "策略因子",
}


def signal_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for row in rows:
        metrics = row.get("metrics") or {}
        metric_1d = metrics.get("1d") or {}
        metric_5d = metrics.get("5d") or {}
        metric_20d = metrics.get("20d") or {}
        metric_60d = metrics.get("60d") or {}
        values = signal_metric_values(metric_1d, metric_5d, metric_20d, metric_60d)
        tags = signal_tags(values)
        if not tags and abs(values["flow_5d"]) < 1:
            continue
        candidates.append(signal_payload(row, values, tags))
    return sorted(candidates, key=lambda item: item["score"], reverse=True)


def signal_metric_values(
    metric_1d: dict[str, Any],
    metric_5d: dict[str, Any],
    metric_20d: dict[str, Any],
    metric_60d: dict[str, Any],
) -> dict[str, Any]:
    return {
        "flow_1d": number(metric_1d.get("flow_yi")),
        "flow_5d": number(metric_5d.get("flow_yi")),
        "flow_20d": number(metric_20d.get("flow_yi")),
        "flow_60d": number(metric_60d.get("flow_yi")),
        "flow_ratio_1d": nullable_number(metric_1d.get("flow_ratio_pct")),
        "flow_ratio_5d": nullable_number(metric_5d.get("flow_ratio_pct")),
        "flow_ratio_20d": nullable_number(metric_20d.get("flow_ratio_pct")),
        "flow_ratio_60d": nullable_number(metric_60d.get("flow_ratio_pct")),
        "change_1d": nullable_number(metric_1d.get("change_window_pct")),
        "change_5d": nullable_number(metric_5d.get("change_window_pct")),
        "change_20d": nullable_number(metric_20d.get("change_window_pct")),
        "change_60d": nullable_number(metric_60d.get("change_window_pct")),
        "turnover_1d": nullable_number(metric_1d.get("turnover_window_avg_pct")),
        "turnover_5d": nullable_number(metric_5d.get("turnover_window_avg_pct")),
        "turnover_20d": nullable_number(metric_20d.get("turnover_window_avg_pct")),
        "turnover_60d": nullable_number(metric_60d.get("turnover_window_avg_pct")),
        "scale_yi": metric_1d.get("scale_yi") or metric_60d.get("scale_yi"),
    }


def signal_tags(values: dict[str, Any]) -> list[str]:
    tags = []
    if values["flow_5d"] > 0 and values["flow_20d"] > 0:
        tags.append("连续流入")
    if values["flow_5d"] < 0 and values["flow_20d"] < 0:
        tags.append("持续流出")
    if values["flow_5d"] > 0 and values["flow_20d"] < 0:
        tags.append("短线回流")
    if values["flow_5d"] < 0 and values["flow_20d"] > 0:
        tags.append("短线转弱")
    if values["flow_5d"] > 0 and values["change_5d"] is not None and values["change_5d"] > 0:
        tags.append("价格确认")
    if values["flow_5d"] > 0 and values["change_5d"] is not None and values["change_5d"] < 0:
        tags.append("逆势承接")
    if values["turnover_5d"] is not None and values["turnover_5d"] >= 5:
        tags.append("成交活跃")
    return tags


def signal_payload(row: dict[str, Any], values: dict[str, Any], tags: list[str]) -> dict[str, Any]:
    score = abs(values["flow_5d"]) + abs(values["flow_20d"]) * 0.4 + abs(values["flow_60d"]) * 0.15
    if values["turnover_5d"] is not None:
        score += min(values["turnover_5d"], 20) * 3
    return {
        "section": row.get("section_label"),
        "name": row.get("name"),
        "title": signal_title(str(row["name"]), values["flow_5d"], values["flow_20d"], values["flow_60d"]),
        "direction": "positive" if values["flow_5d"] >= 0 else "negative",
        "score": round(score, 2),
        "flow_1d_yi": round(values["flow_1d"], 2),
        "flow_5d_yi": round(values["flow_5d"], 2),
        "flow_20d_yi": round(values["flow_20d"], 2),
        "flow_60d_yi": round(values["flow_60d"], 2),
        "flow_ratio_1d_pct": round_nullable(values["flow_ratio_1d"]),
        "flow_ratio_5d_pct": round_nullable(values["flow_ratio_5d"]),
        "flow_ratio_20d_pct": round_nullable(values["flow_ratio_20d"]),
        "flow_ratio_60d_pct": round_nullable(values["flow_ratio_60d"]),
        "change_1d_pct": round_nullable(values["change_1d"]),
        "change_5d_pct": round_nullable(values["change_5d"]),
        "change_20d_pct": round_nullable(values["change_20d"]),
        "change_60d_pct": round_nullable(values["change_60d"]),
        "turnover_1d_avg_pct": round_nullable(values["turnover_1d"]),
        "turnover_5d_avg_pct": round_nullable(values["turnover_5d"]),
        "turnover_20d_avg_pct": round_nullable(values["turnover_20d"]),
        "turnover_60d_avg_pct": round_nullable(values["turnover_60d"]),
        "scale_yi": values["scale_yi"],
        "tags": tags[:4],
    }


def metric_notes() -> dict[str, str]:
    return {
        "flow_Xd_yi": "近X个交易日一级市场ETF净申购金额，单位亿元；X可为1、5、20、60。",
        "flow_ratio_Xd_pct": "近X个交易日净申购金额 / 窗口期初ETF规模，对应表格中的净申购占比。",
        "change_Xd_pct": "近X个交易日复权涨跌幅，由窗口内分天涨跌幅复利合成；只可与同窗口flow_Xd_yi表述为同期。",
        "turnover_Xd_avg_pct": "近X个交易日逐日场内成交额 / 当日期初ETF规模后取均值，对应成交均值占比。",
        "same_window_rule": "只有相同X窗口的flow、change、turnover才能称为同期、共振或背离；禁止用1日涨跌幅解释20日或60日资金。",
        "cross_window_rule": "跨窗口比较只能表述为短线与中期/长期趋势对照，例如5日回流但60日仍流出。",
    }


def compact_row_metrics(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "flow_yi": row.get("net_flow_yi"),
        "flow_ratio_pct": row.get("net_flow_ratio"),
        "change_window_pct": compounded_change_pct(row.get("daily_change_pct") or []),
        "turnover_window_avg_pct": row.get("turnover_ratio"),
        "scale_yi": row.get("scale_yi"),
        "skipped_flow_count": row.get("skipped_flow_count"),
        "close_estimate_count": row.get("close_estimate_count"),
    }


def compact_quality(payload: dict[str, Any]) -> dict[str, Any]:
    etf = payload.get("window_payloads", {}).get("60d", {}).get("etf") or payload.get("etf", {})
    quality = etf.get("quality") or {}
    data_status = etf.get("data_status") or {}
    coverage = etf.get("coverage") or {}
    return {
        "as_of_date": etf.get("latest_date"),
        "price_date": data_status.get("price_date"),
        "share_date": data_status.get("share_date"),
        "nav_date": data_status.get("nav_date"),
        "required_etf_count": data_status.get("required_etf_count"),
        "payload_cache_status": data_status.get("payload_cache_status"),
        "payload_cache_error": data_status.get("payload_cache_error"),
        "nav_backfilled_count": data_status.get("nav_backfilled_count"),
        "nav_estimate_ratio_pct": quality.get("nav_estimate_ratio_pct"),
        "skipped_flow_count": quality.get("skipped_flow_count"),
        "split_adjusted_count": quality.get("split_adjusted_count"),
        "scale_audit": quality.get("scale_audit"),
        "target_coverage_pct": coverage.get("target_coverage_pct"),
    }


def section_totals(payload: dict[str, Any]) -> list[dict[str, Any]]:
    totals = []
    for window_key in WINDOW_KEYS:
        window_payload = payload.get("window_payloads", {}).get(window_key, {})
        north_south = window_payload.get("north_south", {}).get("rows") or []
        for row in north_south:
            totals.append({"window": window_key, "name": row.get("name"), "flow_yi": row.get("net_change_yi")})
        sections = window_payload.get("etf", {}).get("sections", {})
        for section_key, section in sections.items():
            total = sum(number(row.get("net_flow_yi")) for row in section.get("rows") or [])
            totals.append({"window": window_key, "name": SECTION_LABELS.get(section_key, section_key), "flow_yi": round(total, 2)})
    return totals


def section_leaders(payload: dict[str, Any]) -> list[dict[str, Any]]:
    leaders = []
    for window_key in WINDOW_KEYS:
        sections = payload.get("window_payloads", {}).get(window_key, {}).get("etf", {}).get("sections", {})
        for section_key, section in sections.items():
            rows = list(section.get("rows") or [])
            if not rows:
                continue
            leaders.extend(section_direction_leaders(window_key, section_key, rows))
    return leaders


def section_direction_leaders(
    window_key: str,
    section_key: str,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    leaders = []
    for direction, reverse in (("inflow", True), ("outflow", False)):
        row = sorted(rows, key=lambda item: number(item.get("net_flow_yi")), reverse=reverse)[0]
        leaders.append(
            {
                "window": window_key,
                "section": SECTION_LABELS.get(section_key, section_key),
                "direction": direction,
                "name": row.get("display_name") or row.get("index_name"),
                "flow_yi": row.get("net_flow_yi"),
                "flow_ratio_pct": row.get("net_flow_ratio"),
                "change_window_pct": compounded_change_pct(row.get("daily_change_pct") or []),
                "turnover_window_avg_pct": row.get("turnover_ratio"),
            }
        )
    return leaders


def compounded_change_pct(points: list[dict[str, Any]]) -> float | None:
    if not points:
        return None
    factor = 1.0
    has_value = False
    for point in points:
        value = nullable_number(point.get("value"))
        if value is None:
            continue
        factor *= 1 + value / 100
        has_value = True
    return round((factor - 1) * 100, 2) if has_value else None


def signal_title(name: str, flow_5d: float, flow_20d: float, flow_60d: float) -> str:
    if flow_5d > 0 and flow_20d < 0 and flow_60d < 0:
        return f"{name}短线回流"
    if flow_5d < 0 and flow_20d > 0:
        return f"{name}短线转弱"
    if flow_5d > 0 and flow_20d > 0:
        return f"{name}持续流入"
    if flow_5d < 0 and flow_20d < 0:
        return f"{name}持续流出"
    return f"{name}{'流入' if flow_5d >= 0 else '流出'}"


def round_nullable(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def nullable_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
