"""TuShare data access helpers for market-wide capital-flow analysis."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from src.tushare_client import TushareClient, TushareUnavailable


def recent_hsgt_rows(client: TushareClient, min_count: int) -> list[dict[str, Any]]:
    end = yyyymmdd(date.today())
    start = yyyymmdd(date.today() - timedelta(days=120))
    rows = client.query(
        "moneyflow_hsgt",
        {"start_date": start, "end_date": end},
        "trade_date,hgt,sgt,ggt_ss,ggt_sz,north_money,south_money",
    )
    rows = sorted(rows, key=lambda row: str(row.get("trade_date") or ""), reverse=True)
    if len(rows) < min_count:
        raise TushareUnavailable(f"moneyflow_hsgt: expected at least {min_count} recent trading rows")
    return rows


def recent_fund_daily_dates(client: TushareClient, min_count: int) -> list[str]:
    sample_rows = client.query(
        "fund_daily",
        {"ts_code": "510300.SH", "start_date": yyyymmdd(date.today() - timedelta(days=120)), "end_date": yyyymmdd(date.today())},
        "ts_code,trade_date,close",
    )
    dates = sorted(
        {str(row.get("trade_date")) for row in sample_rows if row.get("trade_date")},
        reverse=True,
    )
    if len(dates) >= min_count:
        return dates[:min_count]

    found: list[str] = []
    cursor = date.today()
    for _ in range(90):
        trade_date = yyyymmdd(cursor)
        rows = client.query("fund_daily", {"trade_date": trade_date}, "ts_code,trade_date,close")
        if len(rows) > 100:
            found.append(trade_date)
            if len(found) == min_count:
                return found
        cursor -= timedelta(days=1)
    raise TushareUnavailable(f"fund_daily: cannot find {min_count} recent ETF trading dates")


def fund_daily_map(client: TushareClient, trade_date: str) -> dict[str, float]:
    rows = client.query("fund_daily", {"trade_date": trade_date}, "ts_code,trade_date,close")
    return {str(row["ts_code"]): to_float(row.get("close")) for row in rows if row.get("ts_code")}


def fund_share_map(client: TushareClient, trade_date: str) -> dict[str, float]:
    rows = client.query("fund_share", {"trade_date": trade_date}, "ts_code,trade_date,fd_share")
    return {str(row["ts_code"]): to_float(row.get("fd_share")) for row in rows if row.get("ts_code")}


def fund_nav_map(client: TushareClient, nav_date: str) -> dict[str, float]:
    rows = client.query("fund_nav", {"nav_date": nav_date}, "ts_code,nav_date,unit_nav")
    return {
        str(row["ts_code"]): to_float(row.get("unit_nav"))
        for row in rows
        if row.get("ts_code") and to_float(row.get("unit_nav")) > 0
    }


def fund_basic_map(client: TushareClient) -> dict[str, dict[str, Any]]:
    rows = client.query(
        "fund_basic",
        {"market": "E", "status": "L"},
        "ts_code,name,benchmark,invest_type,market,status",
    )
    return {str(row["ts_code"]): row for row in rows if row.get("ts_code")}


def to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")
