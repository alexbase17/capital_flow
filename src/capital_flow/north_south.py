"""Northbound and southbound capital-flow calculations."""

from __future__ import annotations

from typing import Any

from src.capital_flow.formatting import fmt_date, to_float
from src.capital_flow.policy import HSGT_UNIT_TO_YI


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
