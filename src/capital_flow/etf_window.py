"""ETF window-level flow aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.capital_flow.etf_metrics import (
    classified_group,
    daily_etf_metrics,
    etf_static_info,
    latest_etf_metrics,
)
from src.capital_flow.formatting import fmt_date
from src.capital_flow.grouping import (
    EtfFlowGroup,
    apply_daily_metrics_to_group,
    apply_latest_metrics_to_group,
    etf_top_item,
    flow_price_status_from_counts,
    nav_estimate_ratio_pct,
    price_source_label_from_counts,
    scale_audit_from_groups,
    section_payload,
)
from src.capital_flow.policy import MIN_INDEX_SCALE_YI
from src.capital_flow.price_math import previous_price_for_change
from src.capital_flow.taxonomy import (
    index_code_for_group,
    is_frontend_target_equity_etf,
    is_non_equity_invest_type,
    is_target_equity_etf,
)
from src.capital_flow.types import EtfDailyMetrics, EtfLatestMetrics, EtfStaticInfo
from src.tushare_client import TushareUnavailable


@dataclass(frozen=True)
class EtfWindowContext:
    context_dates: list[str]
    window_dates: list[str]
    latest_date: str
    previous_date: str
    latest_previous_date: str
    latest_prices: dict[str, float]
    latest_navs: dict[str, float]
    latest_previous_prices: dict[str, float]
    latest_previous_shares: dict[str, float]
    latest_shares: dict[str, float]
    start_prices: dict[str, float]
    start_shares: dict[str, float]
    start_navs: dict[str, float]
    daily_prices: dict[str, dict[str, float]]
    daily_navs: dict[str, dict[str, float]]
    daily_shares: dict[str, dict[str, float]]
    daily_amounts: dict[str, dict[str, float]]
    daily_adj_factors: dict[str, dict[str, float]]
    window_days: int


@dataclass
class WindowCoverageCounters:
    total_etf_count: int = 0
    priced_etf_count: int = 0
    target_etf_count: int = 0
    frontend_target_etf_count: int = 0
    non_frontend_target_etf_count: int = 0
    classified_target_etf_count: int = 0
    excluded_non_target_etf_count: int = 0
    skipped_flow_count: int = 0


@dataclass
class EtfWindowAccumulator:
    net_flow_yi: float = 0.0
    nav_count: int = 0
    close_count: int = 0
    skipped_flow_count: int = 0
    split_adjusted_count: int = 0
    last_flow_price: float = 0.0
    last_price_source: str = "close"
    last_price_source_label: str = "收盘价估算"
    latest_flow_share: float | None = None
    previous_flow_share: float | None = None


def etf_flows_for_window(
    funds: dict[str, dict[str, Any]],
    dates: list[str],
    window_days: int,
    *,
    daily_prices: dict[str, dict[str, float]],
    daily_navs: dict[str, dict[str, float]],
    daily_shares: dict[str, dict[str, float]],
    daily_amounts: dict[str, dict[str, float]] | None = None,
    daily_adj_factors: dict[str, dict[str, float]] | None = None,
    data_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = build_window_context(
        dates,
        window_days,
        daily_prices=daily_prices,
        daily_navs=daily_navs,
        daily_shares=daily_shares,
        daily_amounts=daily_amounts or {},
        daily_adj_factors=daily_adj_factors or {},
    )
    groups: dict[tuple[str, str], EtfFlowGroup] = {}
    counters = WindowCoverageCounters()
    for code, fund in funds.items():
        apply_fund_to_window(code, fund, context, groups, counters)
    return etf_window_payload(context, groups, counters, data_status=data_status)


def build_window_context(
    dates: list[str],
    window_days: int,
    *,
    daily_prices: dict[str, dict[str, float]],
    daily_navs: dict[str, dict[str, float]],
    daily_shares: dict[str, dict[str, float]],
    daily_amounts: dict[str, dict[str, float]],
    daily_adj_factors: dict[str, dict[str, float]],
) -> EtfWindowContext:
    if len(dates) < window_days + 1:
        raise TushareUnavailable(f"fund_daily: expected at least {window_days + 1} recent ETF trading dates")
    context_dates = dates[: window_days + 2]
    window_dates = context_dates[: window_days + 1]
    latest_date = window_dates[0]
    previous_date = window_dates[-1]
    latest_previous_date = window_dates[1]
    return EtfWindowContext(
        context_dates=context_dates,
        window_dates=window_dates,
        latest_date=latest_date,
        previous_date=previous_date,
        latest_previous_date=latest_previous_date,
        latest_prices=daily_prices[latest_date],
        latest_navs=daily_navs.get(latest_date, {}),
        latest_previous_prices=daily_prices[latest_previous_date],
        latest_previous_shares=daily_shares[latest_previous_date],
        latest_shares=daily_shares[latest_date],
        start_prices=daily_prices[previous_date],
        start_shares=daily_shares[previous_date],
        start_navs=daily_navs.get(previous_date, {}),
        daily_prices=daily_prices,
        daily_navs=daily_navs,
        daily_shares=daily_shares,
        daily_amounts=daily_amounts,
        daily_adj_factors=daily_adj_factors,
        window_days=window_days,
    )


def apply_fund_to_window(
    code: str,
    fund: dict[str, Any],
    context: EtfWindowContext,
    groups: dict[tuple[str, str], EtfFlowGroup],
    counters: WindowCoverageCounters,
) -> None:
    info = etf_static_info(code, fund)
    if "ETF" not in info.name.upper():
        return
    counters.total_etf_count += 1
    close = context.latest_prices.get(code)
    latest_share = context.latest_shares.get(code)
    if close is None or latest_share is None or close <= 0:
        counters.skipped_flow_count += 1
        return
    counters.priced_etf_count += 1
    classified = frontend_classified_group(info, counters)
    if not classified:
        return
    counters.classified_target_etf_count += 1
    section, index_name = classified
    latest_metrics = latest_metrics_for_window_etf(code, close, latest_share, context)
    group = group_for_classification(groups, section, index_name)
    apply_latest_metrics_to_group(group, latest_metrics)
    accumulator = accumulate_etf_daily_metrics(code, close, context, group, counters)
    group.net_flow_yi += accumulator.net_flow_yi
    group.top_etfs.append(top_item_for_window_etf(code, info, latest_metrics, accumulator))


def frontend_classified_group(
    info: EtfStaticInfo,
    counters: WindowCoverageCounters,
) -> tuple[str, str] | None:
    if is_non_equity_invest_type(info.invest_type):
        counters.excluded_non_target_etf_count += 1
        return None
    if not is_target_equity_etf(info.name, info.benchmark):
        counters.excluded_non_target_etf_count += 1
        return None
    counters.target_etf_count += 1
    if not is_frontend_target_equity_etf(info.name, info.benchmark, info.invest_type):
        counters.non_frontend_target_etf_count += 1
        return None
    counters.frontend_target_etf_count += 1
    return classified_group(info)


def latest_metrics_for_window_etf(
    code: str,
    close: float,
    latest_share: float,
    context: EtfWindowContext,
) -> EtfLatestMetrics:
    latest_previous_share = context.latest_previous_shares.get(code)
    previous_close = context.latest_previous_prices.get(code)
    previous_close_for_change = previous_price_for_change(
        current_price=close,
        previous_price=previous_close,
        previous_share=latest_previous_share,
        older_share=context.daily_shares.get(context.context_dates[2], {}).get(code)
        if len(context.context_dates) > 2
        else None,
    )
    return latest_etf_metrics(
        code=code,
        close=close,
        previous_close=previous_close,
        latest_share=latest_share,
        latest_previous_share=latest_previous_share,
        start_price=context.start_prices.get(code),
        start_share=context.start_shares.get(code),
        latest_navs=context.latest_navs,
        start_navs=context.start_navs,
        latest_adj_factor=context.daily_adj_factors.get(context.latest_date, {}).get(code),
        latest_previous_adj_factor=context.daily_adj_factors.get(context.latest_previous_date, {}).get(code),
        previous_close_for_change=previous_close_for_change,
    )


def group_for_classification(
    groups: dict[tuple[str, str], EtfFlowGroup],
    section: str,
    index_name: str,
) -> EtfFlowGroup:
    key = (section, index_name)
    return groups.setdefault(
        key,
        EtfFlowGroup(section=section, index_name=index_name, index_code=index_code_for_group(section, index_name)),
    )


def accumulate_etf_daily_metrics(
    code: str,
    close: float,
    context: EtfWindowContext,
    group: EtfFlowGroup,
    counters: WindowCoverageCounters,
) -> EtfWindowAccumulator:
    accumulator = EtfWindowAccumulator(last_flow_price=close)
    for day_index in range(context.window_days):
        metrics = window_daily_metrics(code, day_index, context)
        apply_daily_metrics_to_group(group, metrics)
        apply_daily_metrics_to_accumulator(metrics, accumulator, counters, group, day_index)
    return accumulator


def window_daily_metrics(code: str, day_index: int, context: EtfWindowContext) -> EtfDailyMetrics:
    return daily_etf_metrics(
        code=code,
        day_index=day_index,
        window_dates=context.window_dates,
        context_dates=context.context_dates,
        daily_prices=context.daily_prices,
        daily_navs=context.daily_navs,
        daily_shares=context.daily_shares,
        daily_amounts=context.daily_amounts,
        daily_adj_factors=context.daily_adj_factors,
    )


def apply_daily_metrics_to_accumulator(
    metrics: EtfDailyMetrics,
    accumulator: EtfWindowAccumulator,
    counters: WindowCoverageCounters,
    group: EtfFlowGroup,
    day_index: int,
) -> None:
    if metrics.daily_flow_yi is None:
        counters.skipped_flow_count += 1
        accumulator.skipped_flow_count += 1
        return
    accumulator.net_flow_yi += metrics.daily_flow_yi
    accumulator.split_adjusted_count += 1 if metrics.split_adjusted else 0
    if day_index == 0:
        accumulator.latest_flow_share = metrics.current_share
    accumulator.previous_flow_share = metrics.comparable_previous_share
    accumulator.last_flow_price = metrics.comparable_flow_price or accumulator.last_flow_price
    accumulator.last_price_source = metrics.price_source or accumulator.last_price_source
    accumulator.last_price_source_label = metrics.price_source_label or accumulator.last_price_source_label
    if metrics.price_source == "nav":
        group.nav_count += 1
        accumulator.nav_count += 1
    else:
        group.close_estimate_count += 1
        accumulator.close_count += 1


def top_item_for_window_etf(
    code: str,
    info: EtfStaticInfo,
    latest_metrics: EtfLatestMetrics,
    accumulator: EtfWindowAccumulator,
) -> dict[str, Any]:
    price_source_label = (
        price_source_label_from_counts(accumulator.nav_count, accumulator.close_count)
        or accumulator.last_price_source_label
    )
    return etf_top_item(
        code=code,
        name=info.name,
        latest_metrics=latest_metrics,
        net_flow_yi=accumulator.net_flow_yi,
        last_flow_price=accumulator.last_flow_price,
        price_source=accumulator.last_price_source,
        price_source_label=price_source_label,
        latest_flow_share=accumulator.latest_flow_share,
        previous_flow_share=accumulator.previous_flow_share,
        skipped_flow_count=accumulator.skipped_flow_count,
        split_adjusted_count=accumulator.split_adjusted_count,
    )


def etf_window_payload(
    context: EtfWindowContext,
    groups: dict[tuple[str, str], EtfFlowGroup],
    counters: WindowCoverageCounters,
    *,
    data_status: dict[str, Any] | None,
) -> dict[str, Any]:
    nav_count = sum(group.nav_count for group in groups.values())
    close_estimate_count = sum(group.close_estimate_count for group in groups.values())
    return {
        "latest_date": fmt_date(context.latest_date),
        "previous_date": fmt_date(context.previous_date),
        "nav_date": fmt_date(context.latest_date) if context.daily_navs.get(context.latest_date) else None,
        "data_status": data_status or default_data_status(context),
        "total_net_flow_yi": round(sum(group.net_flow_yi for group in groups.values()), 2),
        "coverage": coverage_payload(counters),
        "quality": quality_payload(groups, counters, nav_count, close_estimate_count),
        "sections": sections_payload(groups, context.window_days),
    }


def default_data_status(context: EtfWindowContext) -> dict[str, Any]:
    return {
        "status": "ready",
        "as_of_date": fmt_date(context.latest_date),
        "requested_latest_date": fmt_date(context.latest_date),
        "price_date": fmt_date(context.latest_date),
        "share_date": fmt_date(context.latest_date),
        "nav_date": fmt_date(context.latest_date) if context.daily_navs.get(context.latest_date) else None,
        "is_aligned": True,
        "fallback_reason": None,
    }


def coverage_payload(counters: WindowCoverageCounters) -> dict[str, Any]:
    return {
        "total_etf_count": counters.total_etf_count,
        "priced_etf_count": counters.priced_etf_count,
        "target_equity_etf_count": counters.target_etf_count,
        "frontend_target_equity_etf_count": counters.frontend_target_etf_count,
        "non_frontend_target_equity_etf_count": counters.non_frontend_target_etf_count,
        "classified_target_equity_etf_count": counters.classified_target_etf_count,
        "excluded_non_target_etf_count": counters.excluded_non_target_etf_count,
        "raw_target_coverage_pct": round(counters.classified_target_etf_count / counters.target_etf_count * 100, 2)
        if counters.target_etf_count
        else None,
        "target_coverage_pct": round(
            counters.classified_target_etf_count / counters.frontend_target_etf_count * 100,
            2,
        )
        if counters.frontend_target_etf_count
        else None,
    }


def quality_payload(
    groups: dict[tuple[str, str], EtfFlowGroup],
    counters: WindowCoverageCounters,
    nav_count: int,
    close_estimate_count: int,
) -> dict[str, Any]:
    return {
        "nav_count": nav_count,
        "close_estimate_count": close_estimate_count,
        "skipped_flow_count": counters.skipped_flow_count,
        "split_adjusted_count": sum(group.split_adjusted_count for group in groups.values()),
        "price_source_label": price_source_label_from_counts(nav_count, close_estimate_count) or "--",
        "flow_price_status": flow_price_status_from_counts(nav_count, close_estimate_count),
        "nav_estimate_ratio_pct": nav_estimate_ratio_pct(nav_count, close_estimate_count),
        "scale_audit": scale_audit_from_groups(groups.values()),
    }


def sections_payload(groups: dict[tuple[str, str], EtfFlowGroup], window_days: int) -> dict[str, Any]:
    return {
        "broad": section_payload(
            groups, "broad", "宽基被动ETF净申购金额", min_scale_yi=MIN_INDEX_SCALE_YI, window_days=window_days
        ),
        "a_industry": section_payload(
            groups, "a_industry", "A股行业净申购金额", min_scale_yi=MIN_INDEX_SCALE_YI, window_days=window_days
        ),
        "hk_industry": section_payload(
            groups, "hk_industry", "港股行业净申购金额", min_scale_yi=MIN_INDEX_SCALE_YI, window_days=window_days
        ),
        "strategy": section_payload(
            groups, "strategy", "策略因子ETF净申购金额", min_scale_yi=MIN_INDEX_SCALE_YI, window_days=window_days
        ),
    }
