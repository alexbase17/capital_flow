"""AI-assisted summary generation for the capital-flow dashboard."""

from __future__ import annotations

import json
import re
from typing import Any

from src.config_loader import get_config
from src.http_client import request_json


DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
WINDOW_KEYS = ("1d", "5d", "20d", "60d")
SECTION_LABELS = {
    "broad": "宽基",
    "a_industry": "A股行业",
    "hk_industry": "港股行业",
    "strategy": "策略因子",
}


def capital_flow_ai_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary_input = build_ai_summary_input(payload)
    fallback = rule_based_summary(summary_input)
    api_key = get_config("DEEPSEEK_API_KEY")
    if not api_key:
        return fallback

    model = get_config("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL) or DEFAULT_DEEPSEEK_MODEL
    api_url = get_config("DEEPSEEK_API_URL", DEEPSEEK_API_URL) or DEEPSEEK_API_URL
    try:
        model_summary = request_deepseek_summary(
            summary_input,
            api_key=api_key,
            model=model,
            api_url=api_url,
        )
    except Exception as exc:
        return {
            **fallback,
            "status": "fallback",
            "source": "rules",
            "model": model,
            "error": str(exc),
        }
    return {
        **fallback,
        **model_summary,
        "status": "ready",
        "source": "deepseek",
        "model": model,
    }


def build_ai_summary_input(payload: dict[str, Any]) -> dict[str, Any]:
    rows = merged_rows(payload)
    signals = signal_candidates(rows)
    return {
        "as_of_date": payload.get("etf", {}).get("latest_date"),
        "windows": list(WINDOW_KEYS),
        "quality": compact_quality(payload),
        "totals": section_totals(payload),
        "leaders": section_leaders(payload),
        "signals": signals[:18],
    }


def request_deepseek_summary(
    summary_input: dict[str, Any],
    *,
    api_key: str,
    model: str,
    api_url: str,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是市场资金流向看板的分析助手。只能基于用户提供的结构化数据总结，"
                    "不要编造外部信息，不给买卖建议，不预测收益。输出简体中文 JSON。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": (
                            "请输出简要但关键的关注点。重点识别一级市场净申购、二级市场成交热度、"
                            "当日涨跌幅三者的共振、背离和风险。"
                        ),
                        "schema": {
                            "headline": "一句话总览，35字以内",
                            "focus_items": [
                                {
                                    "title": "关注点标题，16字以内",
                                    "detail": "为什么值得关注，45字以内",
                                    "tags": ["短标签"],
                                }
                            ],
                            "risks": ["需要谨慎解读的数据或背离，最多2条"],
                            "data_quality": "数据质量一句话，35字以内",
                        },
                        "data": summary_input,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        ],
    }
    data = request_json(
        api_url,
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        payload=payload,
        timeout=25,
    )
    content = (
        (data.get("choices") or [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    parsed = parse_model_json(content)
    return normalize_summary(parsed)


def parse_model_json(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    if not text:
        raise ValueError("DeepSeek returned empty summary")
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("DeepSeek summary must be a JSON object")
    return parsed


def normalize_summary(summary: dict[str, Any]) -> dict[str, Any]:
    focus_items = []
    for item in list(summary.get("focus_items") or [])[:5]:
        if not isinstance(item, dict):
            continue
        title = clean_text(item.get("title"), 24)
        detail = clean_text(item.get("detail"), 80)
        if not title or not detail:
            continue
        tags = [clean_text(tag, 10) for tag in list(item.get("tags") or [])[:4]]
        focus_items.append({"title": title, "detail": detail, "tags": [tag for tag in tags if tag]})
    return {
        "headline": clean_text(summary.get("headline"), 60),
        "focus_items": focus_items,
        "risks": [clean_text(item, 80) for item in list(summary.get("risks") or [])[:2] if clean_text(item, 80)],
        "data_quality": clean_text(summary.get("data_quality"), 60),
    }


def rule_based_summary(summary_input: dict[str, Any]) -> dict[str, Any]:
    signals = summary_input.get("signals") or []
    top_positive = next((item for item in signals if item.get("direction") == "positive"), None)
    top_negative = next((item for item in signals if item.get("direction") == "negative"), None)
    focus_items = [focus_item_from_signal(item) for item in signals[:5]]
    focus_items = [item for item in focus_items if item]
    if top_positive and top_negative:
        headline = f"{top_positive['title']}，{top_negative['title']}"
    elif top_positive:
        headline = top_positive["title"]
    else:
        headline = "资金流向整体分化，关注持续性"
    return {
        "status": "ready",
        "source": "rules",
        "model": None,
        "as_of_date": summary_input.get("as_of_date"),
        "headline": headline,
        "focus_items": focus_items[:5],
        "risks": rule_risks(summary_input),
        "data_quality": quality_sentence(summary_input.get("quality") or {}),
    }


def focus_item_from_signal(signal: dict[str, Any]) -> dict[str, Any] | None:
    name = signal.get("name")
    if not name:
        return None
    detail_parts = []
    if signal.get("flow_5d") is not None:
        detail_parts.append(f"5日{round_number(signal.get('flow_5d'))}亿")
    if signal.get("flow_20d") is not None:
        detail_parts.append(f"20日{round_number(signal.get('flow_20d'))}亿")
    if signal.get("change_1d") is not None:
        detail_parts.append(f"当日涨跌{round_number(signal.get('change_1d'))}%")
    if signal.get("turnover_5d") is not None:
        detail_parts.append(f"成交均值{round_number(signal.get('turnover_5d'))}%")
    return {
        "title": signal.get("title") or name,
        "detail": "，".join(detail_parts) or signal.get("reason") or "关注资金、价格和成交变化",
        "tags": signal.get("tags") or [],
    }


def rule_risks(summary_input: dict[str, Any]) -> list[str]:
    quality = summary_input.get("quality") or {}
    risks = []
    if number(quality.get("skipped_flow_count")) > 0:
        risks.append("长窗口含新发或短历史 ETF，60日占比需结合持续性观察")
    if number(quality.get("nav_estimate_ratio_pct")) > 0.5:
        risks.append("少量净值未发布点使用收盘价估算")
    return risks[:2]


def quality_sentence(quality: dict[str, Any]) -> str:
    audit = quality.get("scale_audit") or {}
    estimate = quality.get("nav_estimate_ratio_pct")
    audit_status = audit.get("status") or "--"
    return f"NAV估算占比{round_number(estimate)}%，规模审计{audit_status}"


def merged_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for window_key in WINDOW_KEYS:
        sections = (
            payload.get("window_payloads", {})
            .get(window_key, {})
            .get("etf", {})
            .get("sections", {})
        )
        for section_key, section in sections.items():
            for row in section.get("rows") or []:
                key = (section_key, str(row.get("index_name") or ""), str(row.get("index_code") or ""))
                current = rows_by_key.setdefault(
                    key,
                    {
                        "section": section_key,
                        "section_label": SECTION_LABELS.get(section_key, section_key),
                        "name": row.get("display_name") or row.get("index_name"),
                        "index_code": row.get("index_code") or "",
                        "metrics": {},
                    },
                )
                current["metrics"][window_key] = compact_row_metrics(row)
    return list(rows_by_key.values())


def compact_row_metrics(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "flow_yi": row.get("net_flow_yi"),
        "flow_ratio_pct": row.get("net_flow_ratio"),
        "change_pct": row.get("change_pct"),
        "turnover_ratio_pct": row.get("turnover_ratio"),
        "scale_yi": row.get("scale_yi"),
        "skipped_flow_count": row.get("skipped_flow_count"),
        "close_estimate_count": row.get("close_estimate_count"),
    }


def signal_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for row in rows:
        metrics = row.get("metrics") or {}
        metric_1d = metrics.get("1d") or {}
        metric_5d = metrics.get("5d") or {}
        metric_20d = metrics.get("20d") or {}
        metric_60d = metrics.get("60d") or {}
        flow_5d = number(metric_5d.get("flow_yi"))
        flow_20d = number(metric_20d.get("flow_yi"))
        flow_60d = number(metric_60d.get("flow_yi"))
        change_1d = nullable_number(metric_1d.get("change_pct"))
        turnover_5d = nullable_number(metric_5d.get("turnover_ratio_pct"))
        score = abs(flow_5d) + abs(flow_20d) * 0.4 + abs(flow_60d) * 0.15
        if turnover_5d is not None:
            score += min(turnover_5d, 20) * 3
        tags = []
        if flow_5d > 0 and flow_20d > 0:
            tags.append("连续流入")
        if flow_5d < 0 and flow_20d < 0:
            tags.append("持续流出")
        if flow_5d > 0 and flow_20d < 0:
            tags.append("短线回流")
        if flow_5d < 0 and flow_20d > 0:
            tags.append("短线转弱")
        if flow_5d > 0 and change_1d is not None and change_1d > 0:
            tags.append("价格确认")
        if flow_5d > 0 and change_1d is not None and change_1d < 0:
            tags.append("逆势承接")
        if turnover_5d is not None and turnover_5d >= 5:
            tags.append("成交活跃")
        if not tags and abs(flow_5d) < 1:
            continue
        direction = "positive" if flow_5d >= 0 else "negative"
        title = signal_title(str(row["name"]), flow_5d, flow_20d, flow_60d)
        candidates.append(
            {
                "section": row.get("section_label"),
                "name": row.get("name"),
                "title": title,
                "direction": direction,
                "score": round(score, 2),
                "flow_5d": round(flow_5d, 2),
                "flow_20d": round(flow_20d, 2),
                "flow_60d": round(flow_60d, 2),
                "change_1d": round(change_1d, 2) if change_1d is not None else None,
                "turnover_5d": round(turnover_5d, 2) if turnover_5d is not None else None,
                "scale_yi": metric_1d.get("scale_yi") or metric_60d.get("scale_yi"),
                "tags": tags[:4],
            }
        )
    return sorted(candidates, key=lambda item: item["score"], reverse=True)


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
        "nav_backfilled_count": data_status.get("nav_backfilled_count"),
        "nav_estimate_ratio_pct": quality.get("nav_estimate_ratio_pct"),
        "skipped_flow_count": quality.get("skipped_flow_count"),
        "split_adjusted_count": quality.get("split_adjusted_count"),
        "scale_audit": quality.get("scale_audit"),
        "target_coverage_pct": coverage.get("target_coverage_pct"),
    }


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
            totals.append(
                {
                    "window": window_key,
                    "name": SECTION_LABELS.get(section_key, section_key),
                    "flow_yi": round(total, 2),
                }
            )
    return totals


def section_leaders(payload: dict[str, Any]) -> list[dict[str, Any]]:
    leaders = []
    for window_key in WINDOW_KEYS:
        sections = payload.get("window_payloads", {}).get(window_key, {}).get("etf", {}).get("sections", {})
        for section_key, section in sections.items():
            rows = list(section.get("rows") or [])
            if not rows:
                continue
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
                        "change_pct": row.get("change_pct"),
                        "turnover_ratio_pct": row.get("turnover_ratio"),
                    }
                )
    return leaders


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


def round_number(value: Any) -> str:
    numeric = number(value)
    if abs(numeric) >= 100:
        return f"{numeric:.0f}"
    if abs(numeric) >= 10:
        return f"{numeric:.1f}"
    return f"{numeric:.2f}"


def clean_text(value: Any, max_length: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:max_length]
