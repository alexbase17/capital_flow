"""Capital-flow calculations independent from external data fetching."""

from __future__ import annotations

from typing import Any

from src.capital_flow.formatting import fmt_date, to_float
from src.capital_flow.grouping import (
    EtfFlowGroup,
    apply_daily_metrics_to_group,
    apply_latest_metrics_to_group,
    flow_price_status_from_counts,
    nav_estimate_ratio_pct,
    price_source_label_from_counts,
    scale_audit_from_groups,
    section_payload,
    etf_top_item,
)
from src.capital_flow.north_south import hsgt_item, north_south_flow_from_rows
from src.capital_flow.policy import MIN_INDEX_SCALE_YI
from src.capital_flow.price_math import (
    change_pct_from_adjusted_close,
    change_pct_from_close,
    flow_price_for_etf,
    previous_price_for_change,
    previous_scale_price_for_scale,
    scale_price_for_etf,
    split_adjusted_flow_price,
    split_factor_for_flow_adjustment,
)
from src.capital_flow.taxonomy import (
    classify_etf_group,
    index_code_for_group,
    is_frontend_target_equity_etf,
    is_non_equity_invest_type,
    is_target_equity_etf,
)
from src.capital_flow.types import EtfDailyMetrics, EtfLatestMetrics, EtfStaticInfo
from src.tushare_client import TushareUnavailable


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
    current_date = window_dates[day_index]
    previous_flow_date = window_dates[day_index + 1]
    current_price = daily_prices[current_date].get(code)
    previous_price = daily_prices[previous_flow_date].get(code)
    current_share = daily_shares[current_date].get(code)
    previous_share = daily_shares[previous_flow_date].get(code)
    current_amount_yi = daily_amounts.get(current_date, {}).get(code)
    current_adj_factor = daily_adj_factors.get(current_date, {}).get(code)
    previous_adj_factor = daily_adj_factors.get(previous_flow_date, {}).get(code)
    newer_date = window_dates[day_index - 1] if day_index > 0 else None
    older_date = context_dates[day_index + 2] if day_index + 2 < len(context_dates) else None
    newer_price = daily_prices.get(newer_date, {}).get(code) if newer_date else None
    older_share = daily_shares.get(older_date, {}).get(code) if older_date else None
    share_adjustment = split_factor_for_flow_adjustment(
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
    current_scale_price = (
        split_adjusted_flow_price(
            scale_price_for_etf(code, current_price, daily_navs.get(current_date, {})),
            current_price,
            share_adjustment,
        )
        if current_price is not None
        else None
    )
    audit_current_price = (
        current_price / share_adjustment
        if share_adjustment is not None and current_price is not None
        else current_price
    )
    previous_scale_price = previous_scale_price_for_scale(
        code=code,
        previous_price=previous_price,
        previous_navs=daily_navs.get(previous_flow_date, {}),
        comparable_previous_price=comparable_previous_price,
    )
    daily_change_pct = (
        change_pct_from_adjusted_close(
            current_price,
            previous_price,
            current_adj_factor,
            previous_adj_factor,
            fallback_previous_close=comparable_previous_price,
        )
        if current_price is not None and current_price > 0 and current_share is not None
        else None
    )
    daily_scale_yi = (
        current_share * current_scale_price / 10000
        if daily_change_pct is not None and current_scale_price is not None
        else None
    )
    daily_start_scale_yi = (
        previous_share * previous_scale_price / 10000
        if current_amount_yi is not None
        and current_amount_yi > 0
        and previous_share is not None
        and previous_scale_price is not None
        and previous_scale_price > 0
        else None
    )
    if current_price is None or current_share is None or previous_share is None or current_price <= 0:
        return EtfDailyMetrics(
            current_date=current_date,
            current_price=current_price,
            current_share=current_share,
            previous_share=previous_share,
            daily_change_pct=daily_change_pct,
            daily_scale_yi=daily_scale_yi,
            current_amount_yi=current_amount_yi,
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
    flow_price, price_source, price_source_label = flow_price_for_etf(
        code, current_price, daily_navs.get(current_date, {})
    )
    comparable_previous_share = previous_share * share_adjustment if share_adjustment is not None else previous_share
    comparable_flow_price = split_adjusted_flow_price(flow_price, current_price, share_adjustment)
    daily_flow_yi = (current_share - comparable_previous_share) * comparable_flow_price / 10000
    scale_delta_yi = None
    market_effect_yi = None
    if comparable_previous_price is not None and comparable_previous_price > 0:
        scale_delta_yi = current_share * audit_current_price / 10000 - previous_share * comparable_previous_price / 10000
        market_effect_yi = (
            previous_share * (current_price - previous_price) / 10000
            if share_adjustment is not None and previous_price is not None
            else previous_share * (audit_current_price - comparable_previous_price) / 10000
        )
    return EtfDailyMetrics(
        current_date=current_date,
        current_price=current_price,
        current_share=current_share,
        previous_share=previous_share,
        daily_change_pct=daily_change_pct,
        daily_scale_yi=daily_scale_yi,
        current_amount_yi=current_amount_yi,
        daily_start_scale_yi=daily_start_scale_yi,
        daily_flow_yi=daily_flow_yi,
        scale_delta_yi=scale_delta_yi,
        market_effect_yi=market_effect_yi,
        flow_price=flow_price,
        price_source=price_source,
        price_source_label=price_source_label,
        comparable_flow_price=comparable_flow_price,
        comparable_previous_share=comparable_previous_share,
        split_adjusted=share_adjustment is not None,
    )


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
    if len(dates) < window_days + 1:
        raise TushareUnavailable(f"fund_daily: expected at least {window_days + 1} recent ETF trading dates")
    context_dates = dates[: window_days + 2]
    window_dates = context_dates[: window_days + 1]
    latest_date = window_dates[0]
    previous_date = window_dates[-1]
    latest_prices = daily_prices[latest_date]
    latest_navs = daily_navs.get(latest_date, {})
    latest_previous_date = window_dates[1]
    latest_previous_prices = daily_prices[latest_previous_date]
    latest_previous_shares = daily_shares[latest_previous_date]
    latest_shares = daily_shares[latest_date]
    start_prices = daily_prices[previous_date]
    start_shares = daily_shares[previous_date]
    start_navs = daily_navs.get(previous_date, {})
    daily_amounts = daily_amounts or {}
    daily_adj_factors = daily_adj_factors or {}
    groups: dict[tuple[str, str], EtfFlowGroup] = {}
    total_etf_count = 0
    priced_etf_count = 0
    target_etf_count = 0
    frontend_target_etf_count = 0
    non_frontend_target_etf_count = 0
    classified_target_etf_count = 0
    excluded_non_target_etf_count = 0
    skipped_flow_count = 0
    for code, fund in funds.items():
        info = etf_static_info(code, fund)
        if "ETF" not in info.name.upper():
            continue
        total_etf_count += 1
        close = latest_prices.get(code)
        previous_close = latest_previous_prices.get(code)
        latest_share = latest_shares.get(code)
        latest_previous_share = latest_previous_shares.get(code)
        latest_adj_factor = daily_adj_factors.get(latest_date, {}).get(code)
        latest_previous_adj_factor = daily_adj_factors.get(latest_previous_date, {}).get(code)
        start_price = start_prices.get(code)
        start_share = start_shares.get(code)
        if close is None or latest_share is None or close <= 0:
            skipped_flow_count += 1
            continue
        priced_etf_count += 1
        if is_non_equity_invest_type(info.invest_type):
            excluded_non_target_etf_count += 1
            continue
        is_target = is_target_equity_etf(info.name, info.benchmark)
        if is_target:
            target_etf_count += 1
        else:
            excluded_non_target_etf_count += 1
            continue
        if not is_frontend_target_equity_etf(info.name, info.benchmark, info.invest_type):
            non_frontend_target_etf_count += 1
            continue
        frontend_target_etf_count += 1
        classified = classified_group(info)
        if not classified:
            continue
        classified_target_etf_count += 1
        section, index_name = classified
        previous_close_for_change = previous_price_for_change(
            current_price=close,
            previous_price=previous_close,
            previous_share=latest_previous_share,
            older_share=daily_shares.get(context_dates[2], {}).get(code) if len(context_dates) > 2 else None,
        )
        latest_metrics = latest_etf_metrics(
            code=code,
            close=close,
            previous_close=previous_close,
            latest_share=latest_share,
            latest_previous_share=latest_previous_share,
            start_price=start_price,
            start_share=start_share,
            latest_navs=latest_navs,
            start_navs=start_navs,
            latest_adj_factor=latest_adj_factor,
            latest_previous_adj_factor=latest_previous_adj_factor,
            previous_close_for_change=previous_close_for_change,
        )
        key = (section, index_name)
        group = groups.setdefault(
            key,
            EtfFlowGroup(section=section, index_name=index_name, index_code=index_code_for_group(section, index_name)),
        )
        apply_latest_metrics_to_group(group, latest_metrics)
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
            daily_metrics = daily_etf_metrics(
                code=code,
                day_index=day_index,
                window_dates=window_dates,
                context_dates=context_dates,
                daily_prices=daily_prices,
                daily_navs=daily_navs,
                daily_shares=daily_shares,
                daily_amounts=daily_amounts,
                daily_adj_factors=daily_adj_factors,
            )
            apply_daily_metrics_to_group(group, daily_metrics)
            if daily_metrics.daily_flow_yi is None:
                skipped_flow_count += 1
                etf_skipped_flow_count += 1
                continue
            etf_net_flow_yi += daily_metrics.daily_flow_yi
            if daily_metrics.split_adjusted:
                etf_split_adjusted_count += 1
            if day_index == 0:
                latest_flow_share = daily_metrics.current_share
            previous_flow_share = daily_metrics.comparable_previous_share
            last_flow_price = daily_metrics.comparable_flow_price or last_flow_price
            last_price_source = daily_metrics.price_source or last_price_source
            last_price_source_label = daily_metrics.price_source_label or last_price_source_label
            if daily_metrics.price_source == "nav":
                group.nav_count += 1
                etf_nav_count += 1
            else:
                group.close_estimate_count += 1
                etf_close_count += 1
        group.net_flow_yi += etf_net_flow_yi
        price_source_label = price_source_label_from_counts(etf_nav_count, etf_close_count) or last_price_source_label
        group.top_etfs.append(
            etf_top_item(
                code=code,
                name=info.name,
                latest_metrics=latest_metrics,
                net_flow_yi=etf_net_flow_yi,
                last_flow_price=last_flow_price,
                price_source=last_price_source,
                price_source_label=price_source_label,
                latest_flow_share=latest_flow_share,
                previous_flow_share=previous_flow_share,
                skipped_flow_count=etf_skipped_flow_count,
                split_adjusted_count=etf_split_adjusted_count,
            )
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
            "frontend_target_equity_etf_count": frontend_target_etf_count,
            "non_frontend_target_equity_etf_count": non_frontend_target_etf_count,
            "classified_target_equity_etf_count": classified_target_etf_count,
            "excluded_non_target_etf_count": excluded_non_target_etf_count,
            "raw_target_coverage_pct": round(classified_target_etf_count / target_etf_count * 100, 2)
            if target_etf_count
            else None,
            "target_coverage_pct": round(classified_target_etf_count / frontend_target_etf_count * 100, 2)
            if frontend_target_etf_count
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
