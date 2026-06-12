"""TuShare data access helpers for market-wide capital-flow analysis."""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from src.tushare_client import TushareClient, TushareUnavailable


ROOT_DIR = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT_DIR / "data" / "tushare_cache"
RECENT_DATA_CACHE_SECONDS = 30 * 60
REFERENCE_DATA_CACHE_SECONDS = 24 * 60 * 60
RECENT_TRADE_DATE_DAYS = 10


def recent_hsgt_rows(client: TushareClient, min_count: int) -> list[dict[str, Any]]:
    rows = cached_json(
        f"moneyflow_hsgt/recent_{min_count}",
        lambda: _recent_hsgt_rows_uncached(client, min_count),
        max_age_seconds=RECENT_DATA_CACHE_SECONDS,
    )
    rows = list(rows)
    rows = sorted(rows, key=lambda row: str(row.get("trade_date") or ""), reverse=True)
    if len(rows) < min_count:
        raise TushareUnavailable(f"moneyflow_hsgt: expected at least {min_count} recent trading rows")
    return rows


def _recent_hsgt_rows_uncached(client: TushareClient, min_count: int) -> list[dict[str, Any]]:
    end = yyyymmdd(date.today())
    start = yyyymmdd(date.today() - timedelta(days=120))
    return client.query(
        "moneyflow_hsgt",
        {"start_date": start, "end_date": end},
        "trade_date,hgt,sgt,ggt_ss,ggt_sz,north_money,south_money",
    )


def recent_fund_daily_dates(client: TushareClient, min_count: int) -> list[str]:
    return list(
        cached_json(
            f"fund_daily/recent_dates_{min_count}",
            lambda: _recent_fund_daily_dates_uncached(client, min_count),
            max_age_seconds=RECENT_DATA_CACHE_SECONDS,
        )
    )


def _recent_fund_daily_dates_uncached(client: TushareClient, min_count: int) -> list[str]:
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
    return cached_map(
        f"fund_daily/{trade_date}",
        lambda: _fund_daily_map_uncached(client, trade_date),
        max_age_seconds=dated_cache_ttl(trade_date),
    )


def fund_share_map(client: TushareClient, trade_date: str) -> dict[str, float]:
    return cached_map(
        f"fund_share/{trade_date}",
        lambda: _fund_share_map_uncached(client, trade_date),
        max_age_seconds=dated_cache_ttl(trade_date),
    )


def fund_nav_map(client: TushareClient, nav_date: str) -> dict[str, float]:
    return cached_map(
        f"fund_nav/{nav_date}",
        lambda: _fund_nav_map_uncached(client, nav_date),
        max_age_seconds=dated_cache_ttl(nav_date),
        cache_empty=True,
    )


def _fund_daily_map_uncached(client: TushareClient, trade_date: str) -> dict[str, float]:
    rows = client.query("fund_daily", {"trade_date": trade_date}, "ts_code,trade_date,close")
    return {str(row["ts_code"]): to_float(row.get("close")) for row in rows if row.get("ts_code")}


def _fund_share_map_uncached(client: TushareClient, trade_date: str) -> dict[str, float]:
    rows = client.query("fund_share", {"trade_date": trade_date}, "ts_code,trade_date,fd_share")
    return {str(row["ts_code"]): to_float(row.get("fd_share")) for row in rows if row.get("ts_code")}


def _fund_nav_map_uncached(client: TushareClient, nav_date: str) -> dict[str, float]:
    rows = client.query("fund_nav", {"nav_date": nav_date}, "ts_code,nav_date,unit_nav")
    return {
        str(row["ts_code"]): to_float(row.get("unit_nav"))
        for row in rows
        if row.get("ts_code") and to_float(row.get("unit_nav")) > 0
    }


def fund_basic_map(client: TushareClient) -> dict[str, dict[str, Any]]:
    rows = cached_json("fund_basic/market_E_status_L", lambda: _fund_basic_rows_uncached(client), max_age_seconds=REFERENCE_DATA_CACHE_SECONDS)
    return {str(row["ts_code"]): row for row in rows if row.get("ts_code")}


def _fund_basic_rows_uncached(client: TushareClient) -> list[dict[str, Any]]:
    return client.query(
        "fund_basic",
        {"market": "E", "status": "L"},
        "ts_code,name,benchmark,invest_type,market,status",
    )


def index_classify_rows(client: TushareClient, src: str = "SW2021") -> list[dict[str, Any]]:
    return list(
        cached_json(
            f"index_classify/{src}",
            lambda: client.query("index_classify", {"src": src}, "index_code,industry_name,level,industry_code,src"),
            max_age_seconds=REFERENCE_DATA_CACHE_SECONDS,
        )
    )


def index_member_rows(client: TushareClient, index_code: str) -> list[dict[str, Any]]:
    return list(
        cached_json(
            f"index_member/{index_code}",
            lambda: client.query("index_member", {"index_code": index_code}, "index_code,con_code,in_date,out_date,is_new"),
            max_age_seconds=REFERENCE_DATA_CACHE_SECONDS,
        )
    )


def index_basic_rows(client: TushareClient, market: str) -> list[dict[str, Any]]:
    return list(
        cached_json(
            f"index_basic/{market}",
            lambda: client.query("index_basic", {"market": market}, "ts_code,name,market,publisher,category"),
            max_age_seconds=REFERENCE_DATA_CACHE_SECONDS,
        )
    )


def index_weight_rows(
    client: TushareClient,
    index_code: str,
    *,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    return list(
        cached_json(
            f"index_weight/{index_code}_{start_date}_{end_date}",
            lambda: client.query(
                "index_weight",
                {"index_code": index_code, "start_date": start_date, "end_date": end_date},
                "index_code,con_code,trade_date,weight",
            ),
            max_age_seconds=dated_cache_ttl(end_date),
        )
    )


def cached_map(
    cache_key: str,
    loader,
    *,
    max_age_seconds: int | None,
    cache_empty: bool = False,
) -> dict[str, float]:
    payload = cached_json(cache_key, loader, max_age_seconds=max_age_seconds, cache_empty=cache_empty)
    return {str(key): to_float(value) for key, value in dict(payload).items()}


def cached_json(
    cache_key: str,
    loader,
    *,
    max_age_seconds: int | None,
    cache_empty: bool = True,
) -> Any:
    if file_cache_disabled():
        return loader()
    cache_path = cache_file_path(cache_key)
    cached = read_cache(cache_path, max_age_seconds=max_age_seconds)
    if cached is not None:
        return cached
    payload = loader()
    if cache_empty or payload:
        write_cache(cache_path, payload)
    return payload


def read_cache(path: Path, *, max_age_seconds: int | None) -> Any | None:
    try:
        if max_age_seconds is not None:
            age_seconds = date_time_now() - path.stat().st_mtime
            if age_seconds > max_age_seconds:
                return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_cache(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp_path.replace(path)


def cache_file_path(cache_key: str) -> Path:
    safe_parts = [part.replace("/", "_").replace("..", "_") for part in cache_key.split("/")]
    return CACHE_DIR.joinpath(*safe_parts).with_suffix(".json")


def dated_cache_ttl(yyyymmdd_value: str) -> int | None:
    parsed = parse_yyyymmdd(yyyymmdd_value)
    if parsed is None:
        return RECENT_DATA_CACHE_SECONDS
    if parsed >= date.today() - timedelta(days=RECENT_TRADE_DATE_DAYS):
        return RECENT_DATA_CACHE_SECONDS
    return None


def parse_yyyymmdd(value: str) -> date | None:
    text = str(value or "")
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError:
        return None


def date_time_now() -> float:
    from time import time

    return time()


def file_cache_disabled() -> bool:
    return os.environ.get("CAPITAL_FLOW_DISABLE_FILE_CACHE") == "1"


def to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")
