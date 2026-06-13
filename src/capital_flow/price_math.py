"""ETF price, return, split, and flow-price helpers."""

from __future__ import annotations

from src.capital_flow.policy import SPLIT_FACTORS, SPLIT_PRICE_TOLERANCE, SPLIT_SHARE_TOLERANCE


def flow_price_for_etf(code: str, close: float, latest_navs: dict[str, float]) -> tuple[float, str, str]:
    nav = latest_navs.get(code)
    if nav is not None and nav > 0:
        return nav, "nav", "净值口径"
    return close, "close", "收盘价估算"


def scale_price_for_etf(code: str, close: float | None, navs: dict[str, float]) -> float | None:
    nav = navs.get(code)
    if nav is not None and nav > 0:
        return nav
    return close if close is not None and close > 0 else None


def previous_scale_price_for_scale(
    *,
    code: str,
    previous_price: float | None,
    previous_navs: dict[str, float],
    comparable_previous_price: float | None,
) -> float | None:
    previous_scale_price = scale_price_for_etf(code, previous_price, previous_navs)
    if previous_scale_price is None:
        return comparable_previous_price
    if (
        comparable_previous_price is not None
        and previous_price is not None
        and previous_scale_price == previous_price
        and not ratio_close(comparable_previous_price, previous_price, 0.000001)
    ):
        return comparable_previous_price
    return previous_scale_price


def split_factor_for_flow_adjustment(
    *,
    current_share: float | None,
    previous_share: float | None,
    current_price: float | None,
    newer_price: float | None,
) -> float | None:
    if (
        current_share is None
        or previous_share is None
        or current_price is None
        or newer_price is None
        or current_share <= 0
        or previous_share <= 0
        or current_price <= 0
        or newer_price <= 0
    ):
        return None
    share_ratio = current_share / previous_share
    price_ratio = newer_price / current_price
    for share_multiplier in share_adjustment_multipliers():
        if ratio_close(share_ratio, share_multiplier, SPLIT_SHARE_TOLERANCE) and ratio_close(
            price_ratio, 1 / share_multiplier, SPLIT_PRICE_TOLERANCE
        ):
            return share_multiplier
    return None


def previous_price_for_change(
    *,
    current_price: float | None,
    previous_price: float | None,
    previous_share: float | None,
    older_share: float | None,
) -> float | None:
    if (
        current_price is None
        or previous_price is None
        or previous_share is None
        or older_share is None
        or current_price <= 0
        or previous_price <= 0
        or previous_share <= 0
        or older_share <= 0
    ):
        return previous_price
    share_ratio = previous_share / older_share
    price_ratio = current_price / previous_price
    for share_multiplier in share_adjustment_multipliers():
        if ratio_close(share_ratio, share_multiplier, SPLIT_SHARE_TOLERANCE) and ratio_close(
            price_ratio, 1 / share_multiplier, SPLIT_PRICE_TOLERANCE
        ):
            return previous_price / share_multiplier
    return previous_price


def split_adjusted_flow_price(flow_price: float, current_price: float, share_adjustment: float | None) -> float:
    if share_adjustment is None:
        return flow_price
    if flow_price > 0 and current_price > 0 and ratio_close(
        flow_price / current_price, 1 / share_adjustment, SPLIT_PRICE_TOLERANCE
    ):
        return flow_price
    return flow_price / share_adjustment


def share_adjustment_multipliers() -> tuple[float, ...]:
    return tuple(float(factor) for factor in SPLIT_FACTORS) + tuple(1 / factor for factor in SPLIT_FACTORS)


def ratio_close(value: float, target: float, tolerance: float) -> bool:
    return target > 0 and abs(value - target) / target <= tolerance


def change_pct_from_adjusted_close(
    close: float,
    previous_close: float | None,
    adj_factor: float | None,
    previous_adj_factor: float | None,
    *,
    fallback_previous_close: float | None = None,
) -> float | None:
    if previous_close is None or previous_close <= 0:
        return None
    if adj_factor is not None and previous_adj_factor is not None and adj_factor > 0 and previous_adj_factor > 0:
        adjusted_close = close * adj_factor
        adjusted_previous_close = previous_close * previous_adj_factor
        if adjusted_previous_close > 0:
            return (adjusted_close - adjusted_previous_close) / adjusted_previous_close * 100
    return change_pct_from_close(close, fallback_previous_close if fallback_previous_close is not None else previous_close)


def change_pct_from_close(close: float, previous_close: float | None) -> float | None:
    if previous_close is None or previous_close <= 0:
        return None
    return (close - previous_close) / previous_close * 100
