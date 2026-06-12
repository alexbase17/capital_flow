#!/usr/bin/env python3
"""Print ETF taxonomy coverage and confidence diagnostics."""

from __future__ import annotations

import json
import sys
from pathlib import Path
import argparse


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from src.capital_flow.fetcher import fund_basic_map, fund_daily_map, fund_share_map, recent_fund_daily_dates
from src.capital_flow.taxonomy import EXACT_BENCHMARK_RECORDS
from src.capital_flow.taxonomy_audit import audit_fund_taxonomy
from src.capital_flow.taxonomy_exposure import a_share_benchmark_impacts, a_share_sw_exposure_audit
from src.tushare_client import TushareClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Print ETF taxonomy coverage and confidence diagnostics.")
    parser.add_argument("--with-sw-exposure", action="store_true", help="include A-share SW2021 constituent exposure checks")
    parser.add_argument("--exposure-limit", type=int, default=30, help="maximum indexes to query for exposure checks")
    parser.add_argument("--sample-limit", type=int, default=40, help="maximum samples shown in each audit bucket")
    args = parser.parse_args()

    client = TushareClient.from_env()
    funds = fund_basic_map(client)
    audit = audit_fund_taxonomy(funds, sample_limit=args.sample_limit)
    if args.with_sw_exposure:
        latest_fund_date = recent_fund_daily_dates(client, 1)[0]
        benchmark_impacts = a_share_benchmark_impacts(
            funds,
            fund_daily_map(client, latest_fund_date),
            fund_share_map(client, latest_fund_date),
            sample_limit=5,
        )
        sw_exposure = a_share_sw_exposure_audit(
            client,
            EXACT_BENCHMARK_RECORDS,
            max_indexes=args.exposure_limit,
            sample_limit=args.sample_limit,
            benchmark_impacts=benchmark_impacts,
        )
        audit["sw2021_exposure"] = {
            **sw_exposure,
            "impact_date": f"{latest_fund_date[:4]}-{latest_fund_date[4:6]}-{latest_fund_date[6:]}",
        }
    print(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
