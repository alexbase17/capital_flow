"""Single-ETF metric calculations for capital-flow windows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.capital_flow.price_math import (
    change_pct_from_adjusted_close,
    flow_price_for_etf,
    previous_price_for_change,
    previous_scale_price_for_scale,
    scale_price_for_etf,
    split_adjusted_flow_price,
    split_factor_for_flow_adjustment,
)
from src.capital_flow.taxonomy import classify_etf_group
from src.capital_flow.types import EtfDailyMetrics, EtfLatestMetrics, EtfStaticInfo


@dataclass(frozen=True)
class DailyMetricSource:
    current_date: str
    previous_flow_date: str
    current_price: float | None
    previous_price: float | None
    current_share: float | None
    previous_share: float | None
    current_amount_yi: float | None
    current_adj_factor: float | None
    previous_adj_factor: float | None
    newer_price: float | None
    older_share: float | None


@dataclass(frozen=True)
class DailyScaleValues:
    share_adjustment: float | None
    comparable_previous_price: float | None
    current_scale_price: float | None
    audit_current_price: float | None
    previous_scale_price: float | None


def etf_static_info(code: str, fund: dict[str, Any]) -> EtfStaticInfo:
    return EtfStaticInfo(
        code=code,
        name=str(fund.get("name") or ""),
        benchmark=str(fund.get("benchmark") or ""),
        invest_type=str(fund.get("invest_type") or ""),
    )


def classified_group(info: EtfStaticInfo) -> tuple[str, str] | None:
    return classify_etf_group(info.name, benchmark=info.benchmark, invest_type=info.invest_type)


def latest_etf_metrics(
    *,
    code: str,
    close: float,
    previous_close: float | None,
    latest_share: float,
    latest_previous_share: float | None,
    start_price: float | None,
    start_share: float | None,
    latest_navs: dict[str, float],
    start_navs: dict[str, float],
    latest_adj_factor: float | None,
    latest_previous_adj_factor: float | None,
    previous_close_for_change: float | None,
) -> EtfLatestMetrics:
    latest_scale_price = scale_price_for_etf(code, close, latest_navs)
    start_scale_price = scale_price_for_etf(code, start_price, start_navs)
    scale_yi = latest_share * latest_scale_price / 10000
    start_scale_yi = start_share * start_scale_price / 10000 if start_share is not None and start_scale_price else 0.0
    audit_start_scale_yi = (
        start_share * start_price / 10000
        if start_share is not None and start_price is not None and start_price > 0
        else 0.0
    )
    change_pct = change_pct_from_adjusted_close(
        close,
        previous_close,
        latest_adj_factor,
        latest_previous_adj_factor,
        fallback_previous_close=previous_close_for_change,
    )
    return EtfLatestMetrics(
        close=close,
        previous_close=previous_close,
        latest_share=latest_share,
        latest_previous_share=latest_previous_share,
        scale_yi=scale_yi,
        start_scale_yi=start_scale_yi,
        audit_start_scale_yi=audit_start_scale_yi,
        change_pct=change_pct,
    )


def daily_etf_metrics(
    *,
    code: str,
    day_index: int,
    window_dates: list[str],
    context_dates: list[str],
    daily_prices: dict[str, dict[str, float]],
    daily_navs: dict[str, dict[str, float]],
    daily_shares: dict[str, dict[str, float]],
    daily_amounts: dict[str, dict[str, float]],
    daily_adj_factors: dict[str, dict[str, float]],
) -> EtfDailyMetrics:
    source = daily_metric_source(
        code=code,
        day_index=day_index,
        window_dates=window_dates,
        context_dates=context_dates,
        daily_prices=daily_prices,
        daily_shares=daily_shares,
        daily_amounts=daily_amounts,
        daily_adj_factors=daily_adj_factors,
    )
    scale_values = daily_scale_values(code, source, daily_navs)
    daily_change_pct = daily_change_pct_from_source(source, scale_values)
    daily_scale_yi = daily_scale_yi_from_source(source, scale_values, daily_change_pct)
    daily_start_scale_yi = daily_start_scale_yi_from_source(source, scale_values)
    if source.current_price is None or source.current_share is None or source.previous_share is None or source.current_price <= 0:
        return empty_daily_metrics(source, daily_change_pct, daily_scale_yi, daily_start_scale_yi)
    return populated_daily_metrics(
        code=code,
        source=source,
        scale_values=scale_values,
        daily_navs=daily_navs,
        daily_change_pct=daily_change_pct,
        daily_scale_yi=daily_scale_yi,
        daily_start_scale_yi=daily_start_scale_yi,
    )


def daily_metric_source(
    *,
    code: str,
    day_index: int,
    window_dates: list[str],
    context_dates: list[str],
    daily_prices: dict[str, dict[str, float]],
    daily_shares: dict[str, dict[str, float]],
    daily_amounts: dict[str, dict[str, float]],
    daily_adj_factors: dict[str, dict[str, float]],
) -> DailyMetricSource:
    current_date = window_dates[day_index]
    previous_flow_date = window_dates[day_index + 1]
    newer_date = window_dates[day_index - 1] if day_index > 0 else None
    older_date = context_dates[day_index + 2] if day_index + 2 < len(context_dates) else None
    return DailyMetricSource(
        current_date=current_date,
        previous_flow_date=previous_flow_date,
        current_price=daily_prices[current_date].get(code),
        previous_price=daily_prices[previous_flow_date].get(code),
        current_share=daily_shares[current_date].get(code),
        previous_share=daily_shares[previous_flow_date].get(code),
        current_amount_yi=daily_amounts.get(current_date, {}).get(code),
        current_adj_factor=daily_adj_factors.get(current_date, {}).get(code),
        previous_adj_factor=daily_adj_factors.get(previous_flow_date, {}).get(code),
        newer_price=daily_prices.get(newer_date, {}).get(code) if newer_date else None,
        older_share=daily_shares.get(older_date, {}).get(code) if older_date else None,
    )


def daily_scale_values(
    code: str,
    source: DailyMetricSource,
    daily_navs: dict[str, dict[str, float]],
) -> DailyScaleValues:
    share_adjustment = split_factor_for_flow_adjustment(
        current_share=source.current_share,
        previous_share=source.previous_share,
        current_price=source.current_price,
        newer_price=source.newer_price,
    )
    comparable_previous_price = previous_price_for_change(
        current_price=source.current_price,
        previous_price=source.previous_price,
        previous_share=source.previous_share,
        older_share=source.older_share,
    )
    current_scale_price = (
        split_adjusted_flow_price(
            scale_price_for_etf(code, source.current_price, daily_navs.get(source.current_date, {})),
            source.current_price,
            share_adjustment,
        )
        if source.current_price is not None
        else None
    )
    audit_current_price = (
        source.current_price / share_adjustment
        if share_adjustment is not None and source.current_price is not None
        else source.current_price
    )
    previous_scale_price = previous_scale_price_for_scale(
        code=code,
        previous_price=source.previous_price,
        previous_navs=daily_navs.get(source.previous_flow_date, {}),
        comparable_previous_price=comparable_previous_price,
    )
    return DailyScaleValues(
        share_adjustment=share_adjustment,
        comparable_previous_price=comparable_previous_price,
        current_scale_price=current_scale_price,
        audit_current_price=audit_current_price,
        previous_scale_price=previous_scale_price,
    )


def daily_change_pct_from_source(source: DailyMetricSource, scale_values: DailyScaleValues) -> float | None:
    if source.current_price is None or source.current_price <= 0 or source.current_share is None:
        return None
    return change_pct_from_adjusted_close(
        source.current_price,
        source.previous_price,
        source.current_adj_factor,
        source.previous_adj_factor,
        fallback_previous_close=scale_values.comparable_previous_price,
    )


def daily_scale_yi_from_source(
    source: DailyMetricSource,
    scale_values: DailyScaleValues,
    daily_change_pct: float | None,
) -> float | None:
    if daily_change_pct is None or scale_values.current_scale_price is None or source.current_share is None:
        return None
    return source.current_share * scale_values.current_scale_price / 10000


def daily_start_scale_yi_from_source(source: DailyMetricSource, scale_values: DailyScaleValues) -> float | None:
    if (
        source.current_amount_yi is None
        or source.current_amount_yi <= 0
        or source.previous_share is None
        or scale_values.previous_scale_price is None
        or scale_values.previous_scale_price <= 0
    ):
        return None
    return source.previous_share * scale_values.previous_scale_price / 10000


def empty_daily_metrics(
    source: DailyMetricSource,
    daily_change_pct: float | None,
    daily_scale_yi: float | None,
    daily_start_scale_yi: float | None,
) -> EtfDailyMetrics:
    return EtfDailyMetrics(
        current_date=source.current_date,
        current_price=source.current_price,
        current_share=source.current_share,
        previous_share=source.previous_share,
        daily_change_pct=daily_change_pct,
        daily_scale_yi=daily_scale_yi,
        current_amount_yi=source.current_amount_yi,
        daily_start_scale_yi=daily_start_scale_yi,
        daily_flow_yi=None,
        scale_delta_yi=None,
        market_effect_yi=None,
        flow_price=None,
        price_source=None,
        price_source_label=None,
        comparable_flow_price=None,
        comparable_previous_share=None,
        split_adjusted=False,
    )


def populated_daily_metrics(
    *,
    code: str,
    source: DailyMetricSource,
    scale_values: DailyScaleValues,
    daily_navs: dict[str, dict[str, float]],
    daily_change_pct: float | None,
    daily_scale_yi: float | None,
    daily_start_scale_yi: float | None,
) -> EtfDailyMetrics:
    flow_price, price_source, price_source_label = flow_price_for_etf(
        code, source.current_price, daily_navs.get(source.current_date, {})
    )
    comparable_previous_share = (
        source.previous_share * scale_values.share_adjustment
        if scale_values.share_adjustment is not None
        else source.previous_share
    )
    comparable_flow_price = split_adjusted_flow_price(flow_price, source.current_price, scale_values.share_adjustment)
    daily_flow_yi = (source.current_share - comparable_previous_share) * comparable_flow_price / 10000
    scale_delta_yi, market_effect_yi = daily_scale_audit_values(source, scale_values)
    return EtfDailyMetrics(
        current_date=source.current_date,
        current_price=source.current_price,
        current_share=source.current_share,
        previous_share=source.previous_share,
        daily_change_pct=daily_change_pct,
        daily_scale_yi=daily_scale_yi,
        current_amount_yi=source.current_amount_yi,
        daily_start_scale_yi=daily_start_scale_yi,
        daily_flow_yi=daily_flow_yi,
        scale_delta_yi=scale_delta_yi,
        market_effect_yi=market_effect_yi,
        flow_price=flow_price,
        price_source=price_source,
        price_source_label=price_source_label,
        comparable_flow_price=comparable_flow_price,
        comparable_previous_share=comparable_previous_share,
        split_adjusted=scale_values.share_adjustment is not None,
    )


def daily_scale_audit_values(
    source: DailyMetricSource,
    scale_values: DailyScaleValues,
) -> tuple[float | None, float | None]:
    if scale_values.comparable_previous_price is None or scale_values.comparable_previous_price <= 0:
        return None, None
    scale_delta_yi = (
        source.current_share * scale_values.audit_current_price / 10000
        - source.previous_share * scale_values.comparable_previous_price / 10000
    )
    market_effect_yi = (
        source.previous_share * (source.current_price - source.previous_price) / 10000
        if scale_values.share_adjustment is not None and source.previous_price is not None
        else source.previous_share * (scale_values.audit_current_price - scale_values.comparable_previous_price) / 10000
    )
    return scale_delta_yi, market_effect_yi
