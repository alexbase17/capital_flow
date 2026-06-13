"""Compatibility exports for capital-flow calculations."""

from __future__ import annotations

from src.capital_flow.etf_metrics import (
    classified_group,
    daily_etf_metrics,
    etf_static_info,
    latest_etf_metrics,
)
from src.capital_flow.etf_window import etf_flows_for_window
from src.capital_flow.formatting import fmt_date, to_float
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
from src.capital_flow.north_south import hsgt_item, north_south_flow_from_rows
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


__all__ = [
    "EtfFlowGroup",
    "apply_daily_metrics_to_group",
    "apply_latest_metrics_to_group",
    "change_pct_from_adjusted_close",
    "change_pct_from_close",
    "classified_group",
    "daily_etf_metrics",
    "etf_flows_for_window",
    "etf_static_info",
    "etf_top_item",
    "flow_price_for_etf",
    "flow_price_status_from_counts",
    "fmt_date",
    "hsgt_item",
    "latest_etf_metrics",
    "nav_estimate_ratio_pct",
    "north_south_flow_from_rows",
    "previous_price_for_change",
    "previous_scale_price_for_scale",
    "price_source_label_from_counts",
    "scale_audit_from_groups",
    "scale_price_for_etf",
    "section_payload",
    "split_adjusted_flow_price",
    "split_factor_for_flow_adjustment",
    "to_float",
]
