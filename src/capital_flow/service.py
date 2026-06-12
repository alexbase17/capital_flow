"""Capital-flow dashboard service backed by TuShare public market data."""

from __future__ import annotations

import time
from typing import Any

from src.tushare_client import TushareClient, TushareUnavailable
from src.capital_flow.calculator import (
    EtfFlowGroup,
    MIN_INDEX_SCALE_YI,
    change_pct_from_close,
    etf_flows_for_window,
    flow_price_for_etf,
    hsgt_item,
    north_south_flow_from_rows,
    section_payload,
)
from src.capital_flow.fetcher import (
    fund_basic_map,
    fund_daily_map,
    fund_nav_map,
    fund_share_map,
    recent_fund_daily_dates,
    recent_hsgt_rows,
)
from src.capital_flow.schema import validate_capital_flow_payload


ETF_CACHE_SECONDS = 30 * 60
FLOW_WINDOWS: tuple[tuple[str, str, int], ...] = (
    ("1d", "1日", 1),
    ("3d", "3日", 3),
    ("7d", "7日", 7),
    ("30d", "30日", 30),
)
DEFAULT_FLOW_WINDOW = "1d"


_CACHE: dict[str, Any] = {"payloads": {}}

# Compatibility aliases for focused tests and any local diagnostics.
_change_pct = change_pct_from_close
_etf_flows_for_window = etf_flows_for_window
_flow_price_for_etf = flow_price_for_etf
_fund_basic_map = fund_basic_map
_fund_daily_map = fund_daily_map
_fund_nav_map = fund_nav_map
_fund_share_map = fund_share_map
_hsgt_item = hsgt_item
_north_south_flow_from_rows = north_south_flow_from_rows
_recent_fund_daily_dates = recent_fund_daily_dates
_recent_hsgt_rows = recent_hsgt_rows
_section_payload = section_payload


def capital_flow_payload(
    force_refresh: bool = False,
    client: TushareClient | None = None,
    window_key: str | None = None,
) -> dict[str, Any]:
    selected_window = _window_config(window_key or DEFAULT_FLOW_WINDOW)
    cache_key = selected_window[0]
    now = time.time()
    cached = _CACHE["payloads"].get(cache_key)
    if not force_refresh and cached is not None and now < cached["expires_at"]:
        return cached["payload"]
    payload = _build_capital_flow_payload(client or TushareClient.from_env(), selected_window)
    validate_capital_flow_payload(payload)
    _CACHE["payloads"][cache_key] = {"expires_at": now + ETF_CACHE_SECONDS, "payload": payload}
    return payload


def _build_capital_flow_payload(client: TushareClient, selected_window: tuple[str, str, int]) -> dict[str, Any]:
    if not client.enabled:
        raise TushareUnavailable("TUSHARE_TOKEN is not set")
    key, label, window_days = selected_window
    max_window_days = max(config[2] for config in FLOW_WINDOWS)
    fund_dates = recent_fund_daily_dates(client, max_window_days + 1)
    hsgt_rows = recent_hsgt_rows(client, max_window_days)
    funds = fund_basic_map(client)
    daily_prices = {trade_date: fund_daily_map(client, trade_date) for trade_date in fund_dates}
    daily_navs = {trade_date: fund_nav_map(client, trade_date) for trade_date in fund_dates[:-1]}
    daily_shares = {trade_date: fund_share_map(client, trade_date) for trade_date in fund_dates}
    window_payloads = {}
    for window_config in FLOW_WINDOWS:
        window_key, window_label, configured_days = window_config
        window_payloads[window_key] = {
            "label": window_label,
            "days": configured_days,
            "north_south": north_south_flow_from_rows(hsgt_rows, configured_days),
            "etf": etf_flows_for_window(
                funds,
                fund_dates,
                configured_days,
                daily_prices=daily_prices,
                daily_navs=daily_navs,
                daily_shares=daily_shares,
            ),
        }
    selected_payload = window_payloads[key]
    return {
        "north_south": selected_payload["north_south"],
        "etf": selected_payload["etf"],
        "window_payloads": window_payloads,
        "windows": _window_options(),
        "default_window": DEFAULT_FLOW_WINDOW,
        "selected_window": key,
        "selected_window_label": label,
        "threshold_yi": MIN_INDEX_SCALE_YI,
        "notes": [
            "时间窗口按最近 N 个交易日统计；ETF 净申购金额为窗口内每日份额变动金额累加，北上/南下资金为窗口内每日净额累加。",
            "ETF 每日净申购金额优先按份额变动乘以同日单位净值计算；同日净值缺失时用收盘价估算。",
            "总览并列展示不同资金来源，不直接加总；宽基被动 ETF 排除增强、价值、成长、红利低波等策略变体；A 股行业和港股行业只按跟踪指数归类，未匹配到标准指数规则的 ETF 不纳入行业聚合。",
        ],
    }


def _window_config(window_key: str) -> tuple[str, str, int]:
    for config in FLOW_WINDOWS:
        if config[0] == window_key:
            return config
    return _window_config(DEFAULT_FLOW_WINDOW)


def _window_options() -> dict[str, dict[str, Any]]:
    return {key: {"key": key, "label": label, "days": window_days} for key, label, window_days in FLOW_WINDOWS}


def _latest_two_fund_daily_dates(client: TushareClient) -> tuple[str, str]:
    dates = recent_fund_daily_dates(client, 2)
    return dates[0], dates[1]


def _etf_flows(client: TushareClient) -> dict[str, Any]:
    funds = fund_basic_map(client)
    dates = recent_fund_daily_dates(client, 2)
    return etf_flows_for_window(
        funds,
        dates,
        1,
        daily_prices={trade_date: fund_daily_map(client, trade_date) for trade_date in dates},
        daily_navs={dates[0]: fund_nav_map(client, dates[0])},
        daily_shares={trade_date: fund_share_map(client, trade_date) for trade_date in dates},
    )
