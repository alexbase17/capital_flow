"""Capital-flow calculations independent from external data fetching."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.tushare_client import TushareUnavailable
from src.capital_flow.taxonomy import (
    classify_etf_group,
    index_code_for_group,
    is_target_equity_etf,
)


MIN_INDEX_SCALE_YI = 20.0
HSGT_UNIT_TO_YI = 0.0001
SPLIT_FACTORS = (2, 3, 4, 5, 10)
SPLIT_SHARE_TOLERANCE = 0.12
SPLIT_PRICE_TOLERANCE = 0.18
DISPLAY_INDEX_NAMES = {
    "非银金融": "证券保险/非银金融",
    "电力": "公用事业/电力",
    "家电": "家用电器",
    "建材": "建筑材料",
}


@dataclass
class EtfFlowGroup:
    section: str
    index_name: str
    index_code: str = ""
    net_flow_yi: float = 0.0
    scale_yi: float = 0.0
    start_scale_yi: float = 0.0
    change_weight_yi: float = 0.0
    change_weighted_sum: float = 0.0
    etf_count: int = 0
    nav_count: int = 0
    close_estimate_count: int = 0
    skipped_flow_count: int = 0
    split_adjusted_count: int = 0
    scale_delta_yi: float = 0.0
    audit_net_flow_yi: float = 0.0
    market_effect_yi: float = 0.0
    scale_audit_points: int = 0
    daily_net_flow_yi: dict[str, float] = field(default_factory=dict)
    daily_change_weight_yi: dict[str, float] = field(default_factory=dict)
    daily_change_weighted_sum: dict[str, float] = field(default_factory=dict)
    daily_turnover_yi: dict[str, float] = field(default_factory=dict)
    daily_start_scale_yi: dict[str, float] = field(default_factory=dict)
    top_etfs: list[dict[str, Any]] = field(default_factory=list)


def north_south_flow_from_rows(rows: list[dict[str, Any]], window_days: int) -> dict[str, Any]:
    if len(rows) < window_days:
        return {"latest_date": None, "previous_date": None, "rows": []}
    window_rows = rows[:window_days]
    return {
        "latest_date": fmt_date(window_rows[0]["trade_date"]),
        "previous_date": fmt_date(window_rows[-1]["trade_date"]),
        "rows": [
            hsgt_item("北上资金", window_rows, "north_money"),
            hsgt_item("南下资金", window_rows, "south_money"),
        ],
    }


def hsgt_item(name: str, rows: list[dict[str, Any]], field_name: str) -> dict[str, Any]:
    total_value_yi = sum(to_float(row.get(field_name)) for row in rows) * HSGT_UNIT_TO_YI
    return {
        "name": name,
        "latest_value_yi": round(total_value_yi, 2),
        "net_change_yi": round(total_value_yi, 2),
    }


def etf_flows_for_window(
    funds: dict[str, dict[str, Any]],
    dates: list[str],
    window_days: int,
    *,
    daily_prices: dict[str, dict[str, float]],
    daily_navs: dict[str, dict[str, float]],
    daily_shares: dict[str, dict[str, float]],
    daily_amounts: dict[str, dict[str, float]] | None = None,
    data_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if len(dates) < window_days + 1:
        raise TushareUnavailable(f"fund_daily: expected at least {window_days + 1} recent ETF trading dates")
    context_dates = dates[: window_days + 2]
    window_dates = context_dates[: window_days + 1]
    latest_date = window_dates[0]
    previous_date = window_dates[-1]
    latest_prices = daily_prices[latest_date]
    latest_previous_date = window_dates[1]
    latest_previous_prices = daily_prices[latest_previous_date]
    latest_previous_shares = daily_shares[latest_previous_date]
    latest_shares = daily_shares[latest_date]
    start_prices = daily_prices[previous_date]
    start_shares = daily_shares[previous_date]
    daily_amounts = daily_amounts or {}
    groups: dict[tuple[str, str], EtfFlowGroup] = {}
    total_etf_count = 0
    priced_etf_count = 0
    target_etf_count = 0
    classified_target_etf_count = 0
    excluded_non_target_etf_count = 0
    skipped_flow_count = 0
    for code, fund in funds.items():
        name = str(fund.get("name") or "")
        if "ETF" not in name.upper():
            continue
        total_etf_count += 1
        close = latest_prices.get(code)
        previous_close = latest_previous_prices.get(code)
        latest_share = latest_shares.get(code)
        latest_previous_share = latest_previous_shares.get(code)
        start_price = start_prices.get(code)
        start_share = start_shares.get(code)
        if close is None or latest_share is None or close <= 0:
            skipped_flow_count += 1
            continue
        priced_etf_count += 1
        benchmark = str(fund.get("benchmark") or "")
        invest_type = str(fund.get("invest_type") or "")
        is_target = is_target_equity_etf(name, benchmark)
        if is_target:
            target_etf_count += 1
        else:
            excluded_non_target_etf_count += 1
        classified = classify_etf_group(
            name,
            benchmark=benchmark,
            invest_type=invest_type,
        )
        if not classified:
            continue
        if is_target:
            classified_target_etf_count += 1
        section, index_name = classified
        scale_yi = latest_share * close / 10000
        start_scale_yi = start_share * start_price / 10000 if start_share is not None and start_price is not None and start_price > 0 else 0.0
        previous_close_for_change = previous_price_for_change(
            current_price=close,
            previous_price=previous_close,
            previous_share=latest_previous_share,
            older_share=daily_shares.get(context_dates[2], {}).get(code) if len(context_dates) > 2 else None,
        )
        change_pct = change_pct_from_close(close, previous_close_for_change)
        key = (section, index_name)
        group = groups.setdefault(
            key,
            EtfFlowGroup(section=section, index_name=index_name, index_code=index_code_for_group(section, index_name)),
        )
        group.scale_yi += scale_yi
        group.start_scale_yi += start_scale_yi
        if change_pct is not None:
            group.change_weight_yi += scale_yi
            group.change_weighted_sum += change_pct * scale_yi
        group.etf_count += 1
        etf_net_flow_yi = 0.0
        etf_nav_count = 0
        etf_close_count = 0
        etf_skipped_flow_count = 0
        etf_split_adjusted_count = 0
        last_flow_price = close
        last_price_source = "close"
        last_price_source_label = "收盘价估算"
        latest_flow_share: float | None = None
        previous_flow_share: float | None = None
        for day_index in range(window_days):
            current_date = window_dates[day_index]
            previous_flow_date = window_dates[day_index + 1]
            current_price = daily_prices[current_date].get(code)
            previous_price = daily_prices[previous_flow_date].get(code)
            current_share = daily_shares[current_date].get(code)
            previous_share = daily_shares[previous_flow_date].get(code)
            current_amount_yi = daily_amounts.get(current_date, {}).get(code)
            newer_date = window_dates[day_index - 1] if day_index > 0 else None
            older_date = context_dates[day_index + 2] if day_index + 2 < len(context_dates) else None
            newer_price = daily_prices.get(newer_date, {}).get(code) if newer_date else None
            older_share = daily_shares.get(older_date, {}).get(code) if older_date else None
            split_factor = split_factor_for_flow_adjustment(
                current_share=current_share,
                previous_share=previous_share,
                current_price=current_price,
                newer_price=newer_price,
            )
            comparable_previous_price = previous_price_for_change(
                current_price=current_price,
                previous_price=previous_price,
                previous_share=previous_share,
                older_share=older_share,
            )
            current_scale_price = current_price / split_factor if split_factor and current_price is not None else current_price
            daily_change_pct = (
                change_pct_from_close(current_price, comparable_previous_price)
                if current_price is not None and current_price > 0 and current_share is not None
                else None
            )
            if daily_change_pct is not None:
                daily_scale_yi = current_share * current_scale_price / 10000
                group.daily_change_weight_yi[current_date] = group.daily_change_weight_yi.get(current_date, 0.0) + daily_scale_yi
                group.daily_change_weighted_sum[current_date] = (
                    group.daily_change_weighted_sum.get(current_date, 0.0) + daily_change_pct * daily_scale_yi
                )
            if current_amount_yi is not None and current_amount_yi > 0:
                group.daily_turnover_yi[current_date] = group.daily_turnover_yi.get(current_date, 0.0) + current_amount_yi
                if previous_share is not None and comparable_previous_price is not None and comparable_previous_price > 0:
                    group.daily_start_scale_yi[current_date] = (
                        group.daily_start_scale_yi.get(current_date, 0.0) + previous_share * comparable_previous_price / 10000
                    )
            if current_price is None or current_share is None or previous_share is None or current_price <= 0:
                skipped_flow_count += 1
                group.skipped_flow_count += 1
                etf_skipped_flow_count += 1
                continue
            flow_price, price_source, price_source_label = flow_price_for_etf(
                code, current_price, daily_navs.get(current_date, {})
            )
            comparable_previous_share = previous_share * split_factor if split_factor else previous_share
            comparable_flow_price = split_adjusted_flow_price(flow_price, current_price, split_factor)
            daily_flow_yi = (current_share - comparable_previous_share) * comparable_flow_price / 10000
            etf_net_flow_yi += daily_flow_yi
            group.daily_net_flow_yi[current_date] = group.daily_net_flow_yi.get(current_date, 0.0) + daily_flow_yi
            if split_factor:
                group.split_adjusted_count += 1
                etf_split_adjusted_count += 1
            if comparable_previous_price is not None and comparable_previous_price > 0:
                scale_delta_yi = (
                    current_share * current_scale_price / 10000 - previous_share * comparable_previous_price / 10000
                )
                market_effect_yi = (
                    previous_share * (current_price - previous_price) / 10000
                    if split_factor and previous_price is not None
                    else previous_share * (current_scale_price - comparable_previous_price) / 10000
                )
                group.scale_delta_yi += scale_delta_yi
                group.audit_net_flow_yi += daily_flow_yi
                group.market_effect_yi += market_effect_yi
                group.scale_audit_points += 1
            if day_index == 0:
                latest_flow_share = current_share
                previous_flow_share = comparable_previous_share
            last_flow_price = comparable_flow_price
            last_price_source = price_source
            last_price_source_label = price_source_label
            if price_source == "nav":
                group.nav_count += 1
                etf_nav_count += 1
            else:
                group.close_estimate_count += 1
                etf_close_count += 1
        group.net_flow_yi += etf_net_flow_yi
        price_source_label = price_source_label_from_counts(etf_nav_count, etf_close_count) or last_price_source_label
        group.top_etfs.append(
            {
                "code": code,
                "name": name,
                "scale_yi": round(scale_yi, 2),
                "start_scale_yi": round(start_scale_yi, 2) if start_scale_yi else None,
                "net_flow_yi": round(etf_net_flow_yi, 2),
                "change_pct": round(change_pct, 2) if change_pct is not None else None,
                "flow_price": round(last_flow_price, 4),
                "price_source": last_price_source,
                "price_source_label": price_source_label,
                "latest_share_wan": round(latest_flow_share, 4) if latest_flow_share is not None else None,
                "previous_share_wan": round(previous_flow_share, 4) if previous_flow_share is not None else None,
                "share_change_wan": round(latest_flow_share - previous_flow_share, 4)
                if latest_flow_share is not None and previous_flow_share is not None
                else None,
                "skipped_flow_count": etf_skipped_flow_count,
                "split_adjusted_count": etf_split_adjusted_count,
            }
        )

    sections = {
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
    return {
        "latest_date": fmt_date(latest_date),
        "previous_date": fmt_date(previous_date),
        "nav_date": fmt_date(latest_date) if daily_navs.get(latest_date) else None,
        "data_status": data_status
        or {
            "status": "ready",
            "as_of_date": fmt_date(latest_date),
            "requested_latest_date": fmt_date(latest_date),
            "price_date": fmt_date(latest_date),
            "share_date": fmt_date(latest_date),
            "nav_date": fmt_date(latest_date) if daily_navs.get(latest_date) else None,
            "is_aligned": True,
            "fallback_reason": None,
        },
        "total_net_flow_yi": round(sum(group.net_flow_yi for group in groups.values()), 2),
        "coverage": {
            "total_etf_count": total_etf_count,
            "priced_etf_count": priced_etf_count,
            "target_equity_etf_count": target_etf_count,
            "classified_target_equity_etf_count": classified_target_etf_count,
            "excluded_non_target_etf_count": excluded_non_target_etf_count,
            "target_coverage_pct": round(classified_target_etf_count / target_etf_count * 100, 2)
            if target_etf_count
            else None,
        },
        "quality": {
            "nav_count": sum(group.nav_count for group in groups.values()),
            "close_estimate_count": sum(group.close_estimate_count for group in groups.values()),
            "skipped_flow_count": skipped_flow_count,
            "split_adjusted_count": sum(group.split_adjusted_count for group in groups.values()),
            "price_source_label": price_source_label_from_counts(
                sum(group.nav_count for group in groups.values()),
                sum(group.close_estimate_count for group in groups.values()),
            )
            or "--",
            "flow_price_status": flow_price_status_from_counts(
                sum(group.nav_count for group in groups.values()),
                sum(group.close_estimate_count for group in groups.values()),
            ),
            "nav_estimate_ratio_pct": nav_estimate_ratio_pct(
                sum(group.nav_count for group in groups.values()),
                sum(group.close_estimate_count for group in groups.values()),
            ),
            "scale_audit": scale_audit_from_groups(groups.values()),
        },
        "sections": sections,
    }


def flow_price_for_etf(code: str, close: float, latest_navs: dict[str, float]) -> tuple[float, str, str]:
    nav = latest_navs.get(code)
    if nav is not None and nav > 0:
        return nav, "nav", "净值口径"
    return close, "close", "收盘价估算"


def split_factor_for_flow_adjustment(
    *,
    current_share: float | None,
    previous_share: float | None,
    current_price: float | None,
    newer_price: float | None,
) -> int | None:
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
    for factor in SPLIT_FACTORS:
        if ratio_close(share_ratio, factor, SPLIT_SHARE_TOLERANCE) and ratio_close(
            price_ratio, 1 / factor, SPLIT_PRICE_TOLERANCE
        ):
            return factor
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
    for factor in SPLIT_FACTORS:
        if ratio_close(share_ratio, factor, SPLIT_SHARE_TOLERANCE) and ratio_close(
            price_ratio, 1 / factor, SPLIT_PRICE_TOLERANCE
        ):
            return previous_price / factor
    return previous_price


def split_adjusted_flow_price(flow_price: float, current_price: float, split_factor: int | None) -> float:
    if not split_factor:
        return flow_price
    if flow_price > 0 and current_price > 0 and ratio_close(
        flow_price / current_price, 1 / split_factor, SPLIT_PRICE_TOLERANCE
    ):
        return flow_price
    return flow_price / split_factor


def ratio_close(value: float, target: float, tolerance: float) -> bool:
    return target > 0 and abs(value - target) / target <= tolerance


def change_pct_from_close(close: float, previous_close: float | None) -> float | None:
    if previous_close is None or previous_close <= 0:
        return None
    return (close - previous_close) / previous_close * 100


def section_payload(
    groups: dict[tuple[str, str], EtfFlowGroup],
    section: str,
    title: str,
    min_scale_yi: float | None,
    window_days: int | None = None,
) -> dict[str, Any]:
    rows = [
        group_payload(group, window_days=window_days)
        for (group_section, _), group in groups.items()
        if group_section == section and (min_scale_yi is None or group.scale_yi >= min_scale_yi)
    ]
    rows.sort(key=lambda item: abs(item["net_flow_yi"]), reverse=True)
    return {"title": title, "rows": rows}


def group_payload(group: EtfFlowGroup, *, window_days: int | None = None) -> dict[str, Any]:
    top_etfs = sorted(group.top_etfs, key=lambda item: item["scale_yi"], reverse=True)[:5]
    debug_etfs = sorted(group.top_etfs, key=lambda item: abs(item["net_flow_yi"]), reverse=True)[:10]
    return {
        "index_name": group.index_name,
        "display_name": DISPLAY_INDEX_NAMES.get(group.index_name, group.index_name),
        "index_code": group.index_code,
        "change_pct": round(group.change_weighted_sum / group.change_weight_yi, 2)
        if group.change_weight_yi > 0
        else None,
        "net_flow_yi": round(group.net_flow_yi, 2),
        "net_flow_ratio": round(group.net_flow_yi / group.start_scale_yi * 100, 2) if group.start_scale_yi else None,
        "turnover_yi": round(sum(group.daily_turnover_yi.values()), 2),
        "turnover_ratio": average_daily_turnover_ratio(group.daily_turnover_yi, group.daily_start_scale_yi),
        "scale_yi": round(group.scale_yi, 2),
        "start_scale_yi": round(group.start_scale_yi, 2),
        "etf_count": group.etf_count,
        "nav_count": group.nav_count,
        "close_estimate_count": group.close_estimate_count,
        "skipped_flow_count": group.skipped_flow_count,
        "split_adjusted_count": group.split_adjusted_count,
        "price_source_label": group_price_source_label(group),
        "daily_net_flow": [
            {"date": fmt_date(trade_date), "value": round(value, 2)}
            for trade_date, value in sorted(group.daily_net_flow_yi.items())
        ],
        "daily_change_pct": [
            {"date": fmt_date(trade_date), "value": round(group.daily_change_weighted_sum[trade_date] / weight, 2)}
            for trade_date, weight in sorted(group.daily_change_weight_yi.items())
            if weight > 0
        ],
        "daily_turnover": [
            {
                "date": fmt_date(trade_date),
                "value": round(value, 2),
                "start_scale_yi": round(group.daily_start_scale_yi.get(trade_date, 0.0), 2),
            }
            for trade_date, value in sorted(group.daily_turnover_yi.items())
        ],
        "scale_audit": scale_audit_payload(
            scale_delta_yi=group.scale_delta_yi,
            net_flow_yi=group.audit_net_flow_yi,
            market_effect_yi=group.market_effect_yi,
            start_scale_yi=group.start_scale_yi,
            point_count=group.scale_audit_points,
        ),
        "top_etfs": top_etfs,
        "debug_etfs": debug_etfs,
    }


def group_price_source_label(group: EtfFlowGroup) -> str:
    return price_source_label_from_counts(group.nav_count, group.close_estimate_count) or "--"


def price_source_label_from_counts(nav_count: int, close_estimate_count: int) -> str | None:
    if nav_count > 0 and close_estimate_count == 0:
        return "净值口径"
    if nav_count == 0 and close_estimate_count > 0:
        return "收盘价估算"
    if nav_count > 0 and close_estimate_count > 0:
        return "混合口径"
    return None


def flow_price_status_from_counts(nav_count: int, close_estimate_count: int) -> str:
    if nav_count > 0 and close_estimate_count == 0:
        return "final"
    if nav_count == 0 and close_estimate_count > 0:
        return "estimated"
    if nav_count > 0 and close_estimate_count > 0:
        return "mixed"
    return "unavailable"


def nav_estimate_ratio_pct(nav_count: int, close_estimate_count: int) -> float | None:
    total = nav_count + close_estimate_count
    if total <= 0:
        return None
    return round(close_estimate_count / total * 100, 2)


def average_daily_turnover_ratio(
    daily_turnover_yi: dict[str, float],
    daily_start_scale_yi: dict[str, float],
) -> float | None:
    ratios = [
        turnover_yi / start_scale_yi * 100
        for trade_date, turnover_yi in daily_turnover_yi.items()
        if (start_scale_yi := daily_start_scale_yi.get(trade_date, 0.0)) > 0 and turnover_yi >= 0
    ]
    if not ratios:
        return None
    return round(sum(ratios) / len(ratios), 2)


def scale_audit_from_groups(groups: Any) -> dict[str, Any]:
    group_list = list(groups)
    return scale_audit_payload(
        scale_delta_yi=sum(group.scale_delta_yi for group in group_list),
        net_flow_yi=sum(group.audit_net_flow_yi for group in group_list),
        market_effect_yi=sum(group.market_effect_yi for group in group_list),
        start_scale_yi=sum(group.start_scale_yi for group in group_list),
        point_count=sum(group.scale_audit_points for group in group_list),
    )


def scale_audit_payload(
    *,
    scale_delta_yi: float,
    net_flow_yi: float,
    market_effect_yi: float,
    start_scale_yi: float,
    point_count: int,
) -> dict[str, Any]:
    residual_yi = scale_delta_yi - net_flow_yi - market_effect_yi
    residual_ratio_pct = residual_yi / start_scale_yi * 100 if start_scale_yi else None
    status = "unavailable"
    if point_count > 0:
        status = "ok" if residual_ratio_pct is not None and abs(residual_ratio_pct) <= 0.5 else "review"
    return {
        "status": status,
        "point_count": point_count,
        "scale_delta_yi": round(scale_delta_yi, 2),
        "net_flow_yi": round(net_flow_yi, 2),
        "market_effect_yi": round(market_effect_yi, 2),
        "residual_yi": round(residual_yi, 2),
        "residual_ratio_pct": round(residual_ratio_pct, 2) if residual_ratio_pct is not None else None,
    }


def to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def fmt_date(value: Any) -> str:
    text = str(value or "")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text
