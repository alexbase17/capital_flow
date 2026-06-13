"""AI-assisted summary generation for the capital-flow dashboard."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from src.capital_flow.fetcher import cache_file_path, read_cache, write_cache
from src.capital_flow.policy import AI_SUMMARY_CACHE_SECONDS
from src.config_loader import get_config
from src.http_client import request_json


DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_DEEPSEEK_TIMEOUT_SECONDS = 30
AI_SUMMARY_PROMPT_VERSION = "2026-06-13.3"
WINDOW_KEYS = ("1d", "5d", "20d", "60d")
SECTION_LABELS = {
    "broad": "宽基",
    "a_industry": "A股行业",
    "hk_industry": "港股行业",
    "strategy": "策略因子",
}
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
    payload = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 1200,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是市场资金流向看板的分析助手。只能基于用户提供的结构化数据总结，"
                    "不要编造外部信息，不给买卖建议，不预测收益。必须输出简体中文 JSON，"
                    "不要输出 markdown 或代码块。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": (
                            "任务目标：从用户提供的资金流向数据中，筛选当前最值得关注、"
                            "最能辅助后续观察决策的3-5个信号。不要平均覆盖所有板块，不要机械复述排行榜，"
                            "要优先找出异常、共振、背离、冲突和风格切换。"
                            "优先筛选维度如下；不要求每条关注点全部满足，满足一项且有辅助决策价值即可，"
                            "多个维度同时满足时优先级更高："
                            "1. 金额、净申购占比、涨跌幅、成交均值占比中任一指标显著异常，"
                            "或多指标组合后形成异常的流入、流出、交易热度或价格信号；"
                            "2. 1日、5日、20日、60日多窗口同向强化；"
                            "3. 短线与中长期趋势冲突；"
                            "4. 一级净申购、价格、成交均值占比之间的同窗口共振或背离；"
                            "5. 宽基、A股行业、港股行业、策略因子之间的风格切换或分化；"
                            "6. 资金行为和价格表现明显不一致、需要后续验证的点。"
                            "每条关注点应尽量包含：发生了什么关键数据现象；可能代表什么资金行为；"
                            "后续最应该观察什么变化。如果多个信号属于同一条资金主线，优先合并表达，"
                            "不要拆成多条重复关注点。若没有足够强的信号，请明确说信号偏弱。"
                            "硬约束：只能基于 data 提供的数据，不编造外部信息，不给买卖建议，不预测收益，"
                            "不要写确定性结论。必须严格遵守 data.metric_notes 的字段口径：只有同一窗口的数据"
                            "才能表述为同期、背离或共振，例如 flow_60d_yi 只能和 change_60d_pct、"
                            "turnover_60d_avg_pct 做同期比较；不得用最新1日涨跌幅解释20日或60日资金。"
                            "跨窗口只能表述为短线与中期/长期趋势对照。输出时使用表格一致术语："
                            "一级市场用净申购/净赎回和净申购占比，二级市场用成交均值占比，"
                            "不使用流入强度、成交热度、换手率等容易和表格口径不一致的说法。"
                            "金额单位为亿元，按表格展示习惯保留有效精度：绝对值100亿元及以上不保留小数，"
                            "10到100亿元保留1位小数，10亿元以下最多保留2位小数。"
                            "请按辅助决策价值从高到低排序，最多输出5个关注点；如有需要谨慎解读的点，"
                            "合并进对应关注点 detail，不要单独堆在末尾。"
                        ),
                        "schema": {
                            "headline": "一句话概括最核心资金特征，尽量短",
                            "focus_items": [
                                {
                                    "title": "关注点标题",
                                    "detail": "用一到三句话说明为什么重要、可能代表什么资金行为、下一步观察什么",
                                }
                            ],
                            "risks": [],
                            "data_quality": "可选：仅供后端保留，不会在前端展示",
                        },
                        "json_example": {
                            "headline": "宽基短线回流，行业分化",
                            "focus_items": [
                                {
                                    "title": "沪深300回流",
                                    "detail": "近5日净申购转强，但近20日仍为净赎回，说明短线资金修复尚未完全扭转中期流出。后续重点观察回流能否延续，并和成交均值占比、价格表现形成共振。",
                                }
                            ],
                            "risks": [],
                            "data_quality": "",
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


def metric_notes() -> dict[str, str]:
    return {
        "flow_Xd_yi": "近X个交易日一级市场ETF净申购金额，单位亿元；X可为1、5、20、60。",
        "flow_ratio_Xd_pct": "近X个交易日净申购金额 / 窗口期初ETF规模，对应表格中的净申购占比。",
        "change_Xd_pct": "近X个交易日复权涨跌幅，由窗口内分天涨跌幅复利合成；只可与同窗口flow_Xd_yi表述为同期。",
        "turnover_Xd_avg_pct": "近X个交易日逐日场内成交额 / 当日期初ETF规模后取均值，对应成交均值占比。",
        "same_window_rule": "只有相同X窗口的flow、change、turnover才能称为同期、共振或背离；禁止用1日涨跌幅解释20日或60日资金。",
        "cross_window_rule": "跨窗口比较只能表述为短线与中期/长期趋势对照，例如5日回流但60日仍流出。",
    }


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


def signal_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for row in rows:
        metrics = row.get("metrics") or {}
        metric_1d = metrics.get("1d") or {}
        metric_5d = metrics.get("5d") or {}
        metric_20d = metrics.get("20d") or {}
        metric_60d = metrics.get("60d") or {}
        flow_1d = number(metric_1d.get("flow_yi"))
        flow_5d = number(metric_5d.get("flow_yi"))
        flow_20d = number(metric_20d.get("flow_yi"))
        flow_60d = number(metric_60d.get("flow_yi"))
        flow_ratio_1d = nullable_number(metric_1d.get("flow_ratio_pct"))
        flow_ratio_5d = nullable_number(metric_5d.get("flow_ratio_pct"))
        flow_ratio_20d = nullable_number(metric_20d.get("flow_ratio_pct"))
        flow_ratio_60d = nullable_number(metric_60d.get("flow_ratio_pct"))
        change_1d = nullable_number(metric_1d.get("change_window_pct"))
        change_5d = nullable_number(metric_5d.get("change_window_pct"))
        change_20d = nullable_number(metric_20d.get("change_window_pct"))
        change_60d = nullable_number(metric_60d.get("change_window_pct"))
        turnover_1d = nullable_number(metric_1d.get("turnover_window_avg_pct"))
        turnover_5d = nullable_number(metric_5d.get("turnover_window_avg_pct"))
        turnover_20d = nullable_number(metric_20d.get("turnover_window_avg_pct"))
        turnover_60d = nullable_number(metric_60d.get("turnover_window_avg_pct"))
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
        if flow_5d > 0 and change_5d is not None and change_5d > 0:
            tags.append("价格确认")
        if flow_5d > 0 and change_5d is not None and change_5d < 0:
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
                "flow_1d_yi": round(flow_1d, 2),
                "flow_5d_yi": round(flow_5d, 2),
                "flow_20d_yi": round(flow_20d, 2),
                "flow_60d_yi": round(flow_60d, 2),
                "flow_ratio_1d_pct": round(flow_ratio_1d, 2) if flow_ratio_1d is not None else None,
                "flow_ratio_5d_pct": round(flow_ratio_5d, 2) if flow_ratio_5d is not None else None,
                "flow_ratio_20d_pct": round(flow_ratio_20d, 2) if flow_ratio_20d is not None else None,
                "flow_ratio_60d_pct": round(flow_ratio_60d, 2) if flow_ratio_60d is not None else None,
                "change_1d_pct": round(change_1d, 2) if change_1d is not None else None,
                "change_5d_pct": round(change_5d, 2) if change_5d is not None else None,
                "change_20d_pct": round(change_20d, 2) if change_20d is not None else None,
                "change_60d_pct": round(change_60d, 2) if change_60d is not None else None,
                "turnover_1d_avg_pct": round(turnover_1d, 2) if turnover_1d is not None else None,
                "turnover_5d_avg_pct": round(turnover_5d, 2) if turnover_5d is not None else None,
                "turnover_20d_avg_pct": round(turnover_20d, 2) if turnover_20d is not None else None,
                "turnover_60d_avg_pct": round(turnover_60d, 2) if turnover_60d is not None else None,
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
                        "change_window_pct": compounded_change_pct(row.get("daily_change_pct") or []),
                        "turnover_window_avg_pct": row.get("turnover_ratio"),
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
