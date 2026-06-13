"""AI-assisted summary generation for the capital-flow dashboard."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from src.capital_flow.ai_summary_prompt import deepseek_summary_request_payload
from src.capital_flow.ai_summary_signals import (
    SECTION_LABELS,
    WINDOW_KEYS,
    compact_quality,
    compact_row_metrics,
    metric_notes,
    section_leaders,
    section_totals,
    signal_candidates,
)
from src.capital_flow.fetcher import cache_file_path, read_cache, write_cache
from src.capital_flow.policy import AI_SUMMARY_CACHE_SECONDS
from src.config_loader import get_config
from src.http_client import request_json


DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_DEEPSEEK_TIMEOUT_SECONDS = 30
AI_SUMMARY_PROMPT_VERSION = "2026-06-14.1"
_AI_SUMMARY_CACHE: dict[str, dict[str, Any]] = {}


def capital_flow_ai_summary(
    payload: dict[str, Any],
    *,
    use_deepseek: bool = True,
    use_cache: bool = True,
) -> dict[str, Any]:
    summary_input = build_ai_summary_input(payload)
    empty_summary = hidden_summary(summary_input)
    if not use_deepseek:
        return empty_summary

    api_key = get_config("DEEPSEEK_API_KEY")
    if not api_key:
        return empty_summary

    model = get_config("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL) or DEFAULT_DEEPSEEK_MODEL
    api_url = get_config("DEEPSEEK_API_URL", DEEPSEEK_API_URL) or DEEPSEEK_API_URL
    timeout_seconds = deepseek_timeout_seconds()
    cache_key = ai_summary_cache_key(summary_input, model=model, api_url=api_url)
    if use_cache:
        cached_summary = read_ai_summary_cache(cache_key)
        if cached_summary is not None:
            return cached_summary
    try:
        model_summary = request_deepseek_summary(
            summary_input,
            api_key=api_key,
            model=model,
            api_url=api_url,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        return {
            **empty_summary,
            "status": "unavailable",
            "source": "none",
            "model": model,
            "error": str(exc),
        }
    ready_summary = {
        **model_summary,
        "status": "ready",
        "source": "deepseek",
        "model": model,
    }
    if use_cache:
        write_ai_summary_cache(cache_key, ready_summary)
    return ready_summary


def ai_summary_cache_key(summary_input: dict[str, Any], *, model: str, api_url: str) -> str:
    source = {
        "prompt_version": AI_SUMMARY_PROMPT_VERSION,
        "model": model,
        "api_url": api_url,
        "input": summary_input,
    }
    encoded = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def ai_summary_cache_path(cache_key: str):
    return cache_file_path(f"capital_flow_ai_summary/{cache_key}")


def read_ai_summary_cache(cache_key: str) -> dict[str, Any] | None:
    cached = _AI_SUMMARY_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)
    payload = read_cache(ai_summary_cache_path(cache_key), max_age_seconds=AI_SUMMARY_CACHE_SECONDS)
    if not isinstance(payload, dict):
        return None
    if payload.get("source") != "deepseek" or payload.get("status") != "ready":
        return None
    _AI_SUMMARY_CACHE[cache_key] = dict(payload)
    return dict(payload)


def write_ai_summary_cache(cache_key: str, summary: dict[str, Any]) -> None:
    _AI_SUMMARY_CACHE[cache_key] = dict(summary)
    write_cache(ai_summary_cache_path(cache_key), summary)


def build_ai_summary_input(payload: dict[str, Any]) -> dict[str, Any]:
    rows = merged_rows(payload)
    signals = signal_candidates(rows)
    return {
        "as_of_date": payload.get("etf", {}).get("latest_date"),
        "windows": list(WINDOW_KEYS),
        "metric_notes": metric_notes(),
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
    timeout_seconds: int = DEFAULT_DEEPSEEK_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    payload = deepseek_summary_request_payload(summary_input, model=model)
    data = request_json(
        api_url,
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        payload=payload,
        timeout=timeout_seconds,
    )
    content = (
        (data.get("choices") or [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    parsed = parse_model_json(content)
    return normalize_summary(parsed)


def deepseek_timeout_seconds() -> int:
    raw_value = get_config("DEEPSEEK_TIMEOUT_SECONDS", str(DEFAULT_DEEPSEEK_TIMEOUT_SECONDS))
    try:
        value = int(str(raw_value or "").strip())
    except ValueError:
        return DEFAULT_DEEPSEEK_TIMEOUT_SECONDS
    return min(max(value, 5), 60)


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
        title = clean_summary_text(item.get("title"), 36)
        detail = clean_summary_text(item.get("detail"), 220)
        if not title or not detail:
            continue
        focus_items.append({"title": title, "detail": detail})
    return {
        "headline": clean_summary_text(summary.get("headline"), 80),
        "focus_items": focus_items,
        "risks": [clean_summary_text(item, 140) for item in list(summary.get("risks") or [])[:3] if clean_summary_text(item, 140)],
        "data_quality": clean_summary_text(summary.get("data_quality"), 60),
    }


def hidden_summary(summary_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "hidden",
        "source": "none",
        "model": None,
        "as_of_date": summary_input.get("as_of_date"),
        "headline": "",
        "focus_items": [],
        "risks": [],
        "data_quality": "",
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
    flow_parts = []
    if signal.get("flow_5d_yi") is not None:
        flow_parts.append(flow_phrase("近5日", signal.get("flow_5d_yi")))
    if signal.get("flow_20d_yi") is not None:
        flow_parts.append(flow_phrase("近20日", signal.get("flow_20d_yi")))
    market_parts = []
    if signal.get("change_5d_pct") is not None:
        market_parts.append(f"近5日涨跌幅{round_number(signal.get('change_5d_pct'))}%")
    if signal.get("turnover_5d_avg_pct") is not None:
        market_parts.append(f"近5日成交均值占比{round_number(signal.get('turnover_5d_avg_pct'))}%")
    sentences = []
    if flow_parts:
        sentences.append("、".join(flow_parts))
    if market_parts:
        sentences.append("，".join(market_parts))
    return {
        "title": signal.get("title") or name,
        "detail": "；".join(sentences) + "。" if sentences else signal.get("reason") or "关注资金、价格和成交变化。",
    }


def flow_phrase(window_label: str, value: Any) -> str:
    numeric_value = number(value)
    direction = "净申购" if numeric_value >= 0 else "净赎回"
    return f"{window_label}{direction}{round_number(abs(numeric_value))}亿"


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


def clean_summary_text(value: Any, max_length: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = normalize_yi_amounts(text)
    replacements = {
        "净流入": "净申购",
        "净流出": "净赎回",
        "流入强度": "净申购占比",
        "成交热度": "成交均值占比",
        "成交活跃度": "成交均值占比",
        "换手率": "成交均值占比",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text[:max_length]


def normalize_yi_amounts(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return f"{round_number(match.group(1))}亿"

    return re.sub(r"(?<![\d.])(-?\d+(?:\.\d+)?)\s*亿(?:元)?", replace, text)


def clean_text(value: Any, max_length: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:max_length]
