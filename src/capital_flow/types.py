"""Shared data shapes for capital-flow calculations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict


class FundDailySnapshot(TypedDict, total=False):
    close: float
    amount_yi: float


class EtfTopItem(TypedDict, total=False):
    code: str
    name: str
    scale_yi: float
    start_scale_yi: float | None
    net_flow_yi: float
    change_pct: float | None
    flow_price: float
    price_source: str
    price_source_label: str
    latest_share_wan: float | None
    previous_share_wan: float | None
    share_change_wan: float | None
    skipped_flow_count: int
    split_adjusted_count: int


@dataclass(frozen=True)
class EtfStaticInfo:
    code: str
    name: str
    benchmark: str
    invest_type: str


@dataclass(frozen=True)
class EtfLatestMetrics:
    close: float
    previous_close: float | None
    latest_share: float
    latest_previous_share: float | None
    scale_yi: float
    start_scale_yi: float
    audit_start_scale_yi: float
    change_pct: float | None


@dataclass(frozen=True)
class EtfDailyMetrics:
    current_date: str
    current_price: float | None
    current_share: float | None
    previous_share: float | None
    daily_change_pct: float | None
    daily_scale_yi: float | None
    current_amount_yi: float | None
    daily_start_scale_yi: float | None
    daily_flow_yi: float | None
    scale_delta_yi: float | None
    market_effect_yi: float | None
    flow_price: float | None
    price_source: str | None
    price_source_label: str | None
    comparable_flow_price: float | None
    comparable_previous_share: float | None
    split_adjusted: bool


PayloadDict = dict[str, Any]

