"""ETF group aggregation and payload rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.capital_flow.formatting import fmt_date
from src.capital_flow.types import EtfDailyMetrics, EtfLatestMetrics, EtfTopItem


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
    audit_start_scale_yi: float = 0.0
    scale_audit_points: int = 0
    daily_net_flow_yi: dict[str, float] = field(default_factory=dict)
    daily_change_weight_yi: dict[str, float] = field(default_factory=dict)
    daily_change_weighted_sum: dict[str, float] = field(default_factory=dict)
    daily_turnover_yi: dict[str, float] = field(default_factory=dict)
    daily_start_scale_yi: dict[str, float] = field(default_factory=dict)
    top_etfs: list[dict[str, Any]] = field(default_factory=list)


def apply_latest_metrics_to_group(group: EtfFlowGroup, metrics: EtfLatestMetrics) -> None:
    group.scale_yi += metrics.scale_yi
    group.start_scale_yi += metrics.start_scale_yi
    group.audit_start_scale_yi += metrics.audit_start_scale_yi
    if metrics.change_pct is not None:
        group.change_weight_yi += metrics.scale_yi
        group.change_weighted_sum += metrics.change_pct * metrics.scale_yi
    group.etf_count += 1


def apply_daily_metrics_to_group(group: EtfFlowGroup, metrics: EtfDailyMetrics) -> None:
    if metrics.daily_change_pct is not None and metrics.daily_scale_yi is not None:
        group.daily_change_weight_yi[metrics.current_date] = (
            group.daily_change_weight_yi.get(metrics.current_date, 0.0) + metrics.daily_scale_yi
        )
        group.daily_change_weighted_sum[metrics.current_date] = (
            group.daily_change_weighted_sum.get(metrics.current_date, 0.0)
            + metrics.daily_change_pct * metrics.daily_scale_yi
        )
    if metrics.current_amount_yi is not None and metrics.current_amount_yi > 0:
        group.daily_turnover_yi[metrics.current_date] = (
            group.daily_turnover_yi.get(metrics.current_date, 0.0) + metrics.current_amount_yi
        )
        if metrics.daily_start_scale_yi is not None:
            group.daily_start_scale_yi[metrics.current_date] = (
                group.daily_start_scale_yi.get(metrics.current_date, 0.0) + metrics.daily_start_scale_yi
            )
    if metrics.daily_flow_yi is None:
        group.skipped_flow_count += 1
        return
    group.daily_net_flow_yi[metrics.current_date] = (
        group.daily_net_flow_yi.get(metrics.current_date, 0.0) + metrics.daily_flow_yi
    )
    if metrics.split_adjusted:
        group.split_adjusted_count += 1
    if metrics.scale_delta_yi is not None and metrics.market_effect_yi is not None:
        group.scale_delta_yi += metrics.scale_delta_yi
        group.audit_net_flow_yi += metrics.daily_flow_yi
        group.market_effect_yi += metrics.market_effect_yi
        group.scale_audit_points += 1


def etf_top_item(
    *,
    code: str,
    name: str,
    latest_metrics: EtfLatestMetrics,
    net_flow_yi: float,
    last_flow_price: float,
    price_source: str,
    price_source_label: str,
    latest_flow_share: float | None,
    previous_flow_share: float | None,
    skipped_flow_count: int,
    split_adjusted_count: int,
) -> EtfTopItem:
    return {
        "code": code,
        "name": name,
        "scale_yi": round(latest_metrics.scale_yi, 2),
        "start_scale_yi": round(latest_metrics.start_scale_yi, 2) if latest_metrics.start_scale_yi else None,
        "net_flow_yi": round(net_flow_yi, 2),
        "change_pct": round(latest_metrics.change_pct, 2) if latest_metrics.change_pct is not None else None,
        "flow_price": round(last_flow_price, 4),
        "price_source": price_source,
        "price_source_label": price_source_label,
        "latest_share_wan": round(latest_flow_share, 4) if latest_flow_share is not None else None,
        "previous_share_wan": round(previous_flow_share, 4) if previous_flow_share is not None else None,
        "share_change_wan": round(latest_flow_share - previous_flow_share, 4)
        if latest_flow_share is not None and previous_flow_share is not None
        else None,
        "window_start_share_wan": round(previous_flow_share, 4) if previous_flow_share is not None else None,
        "window_share_change_wan": round(latest_flow_share - previous_flow_share, 4)
        if latest_flow_share is not None and previous_flow_share is not None
        else None,
        "skipped_flow_count": skipped_flow_count,
        "split_adjusted_count": split_adjusted_count,
    }


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
            start_scale_yi=group.audit_start_scale_yi,
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
        start_scale_yi=sum(group.audit_start_scale_yi for group in group_list),
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
