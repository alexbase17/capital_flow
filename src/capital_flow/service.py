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
    fund_adj_history_map,
    fund_adj_map,
    fund_basic_map,
    fund_daily_map,
    fund_daily_snapshot_map,
    fund_nav_map,
    fund_share_map,
    recent_fund_daily_dates,
    recent_hsgt_rows,
)
from src.capital_flow.schema import validate_capital_flow_payload
from src.capital_flow.taxonomy import is_target_equity_etf


ETF_CACHE_SECONDS = 30 * 60
FLOW_WINDOWS: tuple[tuple[str, str, int], ...] = (
    ("1d", "1日", 1),
    ("5d", "5日", 5),
    ("20d", "20日", 20),
    ("60d", "60日", 60),
)
DEFAULT_FLOW_WINDOW = "1d"
FUND_DATE_LOOKBACK_BUFFER = 10


_CACHE: dict[str, Any] = {"payloads": {}}

# Compatibility aliases for focused tests and any local diagnostics.
_change_pct = change_pct_from_close
_etf_flows_for_window = etf_flows_for_window
_flow_price_for_etf = flow_price_for_etf
_fund_adj_history_map = fund_adj_history_map
_fund_adj_map = fund_adj_map
_fund_basic_map = fund_basic_map
_fund_daily_map = fund_daily_map
_fund_daily_snapshot_map = fund_daily_snapshot_map
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
    required_fund_dates = max_window_days + 2
    candidate_fund_dates = recent_fund_daily_dates(client, required_fund_dates + FUND_DATE_LOOKBACK_BUFFER)
    hsgt_rows = recent_hsgt_rows(client, max_window_days)
    funds = fund_basic_map(client)
    candidate_snapshots = {trade_date: fund_daily_snapshot_map(client, trade_date) for trade_date in candidate_fund_dates}
    candidate_prices = {
        trade_date: {code: values.get("close", 0.0) for code, values in snapshot.items()}
        for trade_date, snapshot in candidate_snapshots.items()
    }
    candidate_amounts = {
        trade_date: {code: values.get("amount_yi", 0.0) for code, values in snapshot.items()}
        for trade_date, snapshot in candidate_snapshots.items()
    }
    candidate_shares = {trade_date: fund_share_map(client, trade_date) for trade_date in candidate_fund_dates}
    required_codes = active_target_etf_codes(funds, candidate_prices, candidate_shares, candidate_fund_dates)
    fund_dates, etf_status = aligned_fund_dates(
        candidate_fund_dates,
        candidate_prices,
        candidate_shares,
        required_fund_dates,
        required_codes=required_codes,
    )
    daily_prices = {trade_date: candidate_prices[trade_date] for trade_date in fund_dates}
    daily_amounts = {trade_date: candidate_amounts[trade_date] for trade_date in fund_dates}
    daily_shares = {trade_date: candidate_shares[trade_date] for trade_date in fund_dates}
    daily_navs = {trade_date: fund_nav_map(client, trade_date) for trade_date in fund_dates[:-1]}
    daily_adj_factors = {trade_date: fund_adj_map(client, trade_date) for trade_date in fund_dates}
    fill_missing_adj_factors(
        client,
        daily_adj_factors,
        fund_dates=fund_dates,
        required_codes=required_codes,
        daily_prices=daily_prices,
    )
    etf_status = {**etf_status, "nav_date": fmt_date(fund_dates[0]) if daily_navs.get(fund_dates[0]) else None}
    window_payloads = {}
    for window_config in FLOW_WINDOWS:
        window_key, window_label, configured_days = window_config
        window_dates = fund_dates[: configured_days + 2]
        window_payloads[window_key] = {
            "label": window_label,
            "days": configured_days,
            "north_south": north_south_flow_from_rows(hsgt_rows, configured_days),
            "etf": etf_flows_for_window(
                funds,
                window_dates,
                configured_days,
                daily_prices=daily_prices,
                daily_navs=daily_navs,
                daily_shares=daily_shares,
                daily_amounts=daily_amounts,
                daily_adj_factors=daily_adj_factors,
                data_status=window_etf_status(etf_status, window_dates),
            ),
        }
    selected_payload = window_payloads[key]
    return {
        "data_status": {
            "etf": selected_payload["etf"]["data_status"],
            "north_south": north_south_data_status(hsgt_rows),
        },
        "north_south": selected_payload["north_south"],
        "etf": selected_payload["etf"],
        "window_payloads": window_payloads,
        "windows": _window_options(),
        "default_window": DEFAULT_FLOW_WINDOW,
        "selected_window": key,
        "selected_window_label": label,
        "threshold_yi": MIN_INDEX_SCALE_YI,
        "notes": [
            "时间窗口按最近 N 个交易日统计，页面中的“日”均指 ETF 有效交易日；ETF 净申购金额为窗口内每日份额变动金额累加，北上/南下资金为窗口内每日净额累加。",
            "ETF 每日净申购只使用目标权益 ETF 价格和份额 100% 对齐的交易日；最新交易日数据不完整时自动回退到最近完整交易日。",
            "ETF 每日净申购金额优先按份额变动乘以同日单位净值计算；同日净值缺失时用同日收盘价估算，近期净值发布后会随短 TTL 缓存自动回填。",
            "当日和分天涨跌幅优先使用 fund_adj 复权因子计算，用于处理现金分红、份额分拆、合并和折算对收益序列的影响；ETF 净申购金额不使用复权价。",
            "5日成交均值占比为近 5 个交易日逐日计算场内成交额 / 当日期初 ETF 规模后取均值，用于观察二级市场交易热度。",
            "总览并列展示不同资金来源，不直接加总；宽基被动 ETF 排除增强、价值、成长、红利低波等策略变体；宽基、策略因子、A 股行业和港股行业均只展示聚合规模不低于 20 亿元的项目；A 股行业和港股行业只按跟踪指数归类，未匹配到标准指数规则的 ETF 不纳入行业聚合。",
        ],
    }


def aligned_fund_dates(
    candidate_dates: list[str],
    daily_prices: dict[str, dict[str, float]],
    daily_shares: dict[str, dict[str, float]],
    required_count: int,
    *,
    required_codes: set[str] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    required_codes = required_codes or set()
    as_of_date = next(
        (
            date
            for date in candidate_dates
            if date_has_complete_price_share(date, daily_prices, daily_shares, required_codes, strict_required_codes=True)
        ),
        "",
    )
    if not as_of_date:
        raise TushareUnavailable("ETF price/share data are not fully aligned for target equity ETFs")
    as_of_index = candidate_dates.index(as_of_date)
    usable_dates = [
        date
        for date in candidate_dates[as_of_index:]
        if date_has_complete_price_share(date, daily_prices, daily_shares, required_codes, strict_required_codes=False)
    ]
    if len(usable_dates) < required_count:
        raise TushareUnavailable(
            f"ETF price/share data are not aligned: expected {required_count} complete trading dates"
        )
    requested_latest_date = candidate_dates[0] if candidate_dates else ""
    latest_price_date = next((date for date in candidate_dates if daily_prices.get(date)), "")
    latest_share_date = next((date for date in candidate_dates if daily_shares.get(date)), "")
    status = "ready" if as_of_date == requested_latest_date else "fallback"
    fallback_reason = None
    if status == "fallback":
        fallback_reason = f"最新目标权益 ETF 价格/份额数据未 100% 对齐，已回退到 {fmt_date(as_of_date)}"
    missing_price_count = missing_code_count(daily_prices.get(requested_latest_date, {}), required_codes)
    missing_share_count = missing_code_count(daily_shares.get(requested_latest_date, {}), required_codes)
    return usable_dates[:required_count], {
        "status": status,
        "as_of_date": fmt_date(as_of_date),
        "requested_latest_date": fmt_date(requested_latest_date),
        "latest_price_date": fmt_date(latest_price_date),
        "latest_share_date": fmt_date(latest_share_date),
        "price_date": fmt_date(as_of_date),
        "share_date": fmt_date(as_of_date),
        "nav_date": None,
        "is_aligned": True,
        "fallback_reason": fallback_reason,
        "required_etf_count": len(required_codes),
        "missing_price_count": missing_price_count,
        "missing_share_count": missing_share_count,
    }


_aligned_fund_dates = aligned_fund_dates


def target_etf_codes(funds: dict[str, dict[str, Any]]) -> set[str]:
    codes = set()
    for code, fund in funds.items():
        name = str(fund.get("name") or "")
        if "ETF" not in name.upper():
            continue
        benchmark = str(fund.get("benchmark") or "")
        if is_target_equity_etf(name, benchmark):
            codes.add(code)
    return codes


def active_target_etf_codes(
    funds: dict[str, dict[str, Any]],
    daily_prices: dict[str, dict[str, float]],
    daily_shares: dict[str, dict[str, float]],
    candidate_dates: list[str],
) -> set[str]:
    if not candidate_dates:
        return set()
    latest_date = candidate_dates[0]
    active_codes = set(daily_shares.get(latest_date, {}))
    return target_etf_codes(funds) & active_codes


def date_has_complete_price_share(
    trade_date: str,
    daily_prices: dict[str, dict[str, float]],
    daily_shares: dict[str, dict[str, float]],
    required_codes: set[str],
    *,
    strict_required_codes: bool,
) -> bool:
    prices = daily_prices.get(trade_date) or {}
    shares = daily_shares.get(trade_date) or {}
    if not prices or not shares:
        return False
    if not required_codes or not strict_required_codes:
        return True
    return all(to_positive_float(prices.get(code)) > 0 and to_positive_float(shares.get(code)) > 0 for code in required_codes)


def missing_code_count(values: dict[str, float], required_codes: set[str]) -> int:
    if not required_codes:
        return 0
    return sum(1 for code in required_codes if to_positive_float(values.get(code)) <= 0)


def fill_missing_adj_factors(
    client: TushareClient,
    daily_adj_factors: dict[str, dict[str, float]],
    *,
    fund_dates: list[str],
    required_codes: set[str],
    daily_prices: dict[str, dict[str, float]],
) -> None:
    if not fund_dates or not required_codes:
        return
    missing_codes = {
        code
        for trade_date in fund_dates
        for code in required_codes
        if to_positive_float(daily_prices.get(trade_date, {}).get(code)) > 0
        and to_positive_float(daily_adj_factors.get(trade_date, {}).get(code)) <= 0
    }
    if not missing_codes:
        return
    start_date = fund_dates[-1]
    end_date = fund_dates[0]
    for code in sorted(missing_codes):
        history = fund_adj_history_map(client, code, start_date=start_date, end_date=end_date)
        for trade_date, factor in history.items():
            if (
                trade_date in daily_adj_factors
                and factor > 0
                and to_positive_float(daily_prices.get(trade_date, {}).get(code)) > 0
            ):
                daily_adj_factors[trade_date][code] = factor


def to_positive_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def window_etf_status(base_status: dict[str, Any], window_dates: list[str]) -> dict[str, Any]:
    return {
        **base_status,
        "as_of_date": fmt_date(window_dates[0]) if window_dates else base_status.get("as_of_date"),
        "price_date": fmt_date(window_dates[0]) if window_dates else base_status.get("price_date"),
        "share_date": fmt_date(window_dates[0]) if window_dates else base_status.get("share_date"),
        "previous_date": fmt_date(window_dates[-1]) if window_dates else None,
    }


def north_south_data_status(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latest_date = rows[0].get("trade_date") if rows else ""
    return {
        "status": "ready" if rows else "unavailable",
        "as_of_date": fmt_date(latest_date),
        "is_aligned": True,
    }


def _window_config(window_key: str) -> tuple[str, str, int]:
    for config in FLOW_WINDOWS:
        if config[0] == window_key:
            return config
    return _window_config(DEFAULT_FLOW_WINDOW)


def _window_options() -> dict[str, dict[str, Any]]:
    return {key: {"key": key, "label": label, "days": window_days} for key, label, window_days in FLOW_WINDOWS}


def fmt_date(value: Any) -> str:
    text = str(value or "")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


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
