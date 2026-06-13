import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.capital_flow import fetcher, service
from src.capital_flow.calculator import (
    EtfFlowGroup,
    change_pct_from_close,
    etf_flows_for_window,
    flow_price_for_etf,
    hsgt_item,
    section_payload,
)
from src.capital_flow.fetcher import (
    fund_adj_history_map,
    fund_adj_map,
    fund_nav_history_map,
)
from src.capital_flow.service import (
    aligned_fund_dates,
    active_target_etf_codes,
    fill_missing_adj_factors,
    fill_missing_navs,
)
from src.capital_flow.schema import validate_capital_flow_payload
from src.capital_flow.taxonomy import (
    EXACT_BENCHMARK_RECORDS,
    classify_etf_detail,
    classify_etf_group,
    index_code_for_group,
    is_target_equity_etf,
    load_taxonomy_records,
)
from src.capital_flow.taxonomy_audit import audit_fund_taxonomy
from src.capital_flow.taxonomy_exposure import (
    a_share_benchmark_impacts,
    canonical_index_name,
    index_provider_hint,
    index_name_aliases,
    label_consistency_audit,
    resolve_index_code,
    sw2021_exposure_from_weight_rows,
)
from src.tushare_client import TushareUnavailable


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def read_fixture(filename: str):
    return json.loads((FIXTURE_DIR / filename).read_text(encoding="utf-8"))


def core_accounting_snapshot(payload):
    def row_snapshot(row):
        return {
            key: row[key]
            for key in (
                "change_pct",
                "daily_change_pct",
                "daily_net_flow",
                "daily_turnover",
                "index_code",
                "index_name",
                "net_flow_ratio",
                "net_flow_yi",
                "scale_audit",
                "scale_yi",
                "split_adjusted_count",
                "start_scale_yi",
                "turnover_ratio",
                "turnover_yi",
            )
            if key in row
        }

    return {
        "latest_date": payload["latest_date"],
        "previous_date": payload["previous_date"],
        "quality": payload["quality"],
        "broad_rows": [row_snapshot(row) for row in payload["sections"]["broad"]["rows"]],
        "a_industry_rows": [row_snapshot(row) for row in payload["sections"]["a_industry"]["rows"]],
    }


def minimal_valid_capital_flow_payload(window_key: str = "1d"):
    data_status = {
        "status": "ready",
        "as_of_date": "2026-06-11",
        "price_date": "2026-06-11",
        "share_date": "2026-06-11",
        "nav_date": "2026-06-11",
        "is_aligned": True,
    }
    sections = {
        "broad": {"title": "宽基", "rows": []},
        "strategy": {"title": "策略", "rows": []},
        "a_industry": {"title": "A股", "rows": []},
        "hk_industry": {"title": "港股", "rows": []},
    }
    return {
        "data_status": {"etf": dict(data_status), "north_south": {}},
        "north_south": {"latest_date": "2026-06-11", "previous_date": "2026-06-10", "rows": []},
        "etf": {
            "latest_date": "2026-06-11",
            "previous_date": "2026-06-10",
            "nav_date": "2026-06-11",
            "data_status": dict(data_status),
            "coverage": {},
            "quality": {},
            "sections": sections,
        },
        "windows": {},
        "default_window": "1d",
        "selected_window": window_key,
        "selected_window_label": "1日",
        "window_payloads": {
            window_key: {
                "north_south": {"latest_date": "2026-06-11", "previous_date": "2026-06-11", "rows": []},
                "etf": {"data_status": dict(data_status), "sections": sections},
            }
        },
        "threshold_yi": 20,
        "notes": [],
        "ai_summary": {
            "status": "ready",
            "source": "rules",
            "headline": "资金流向分化",
            "focus_items": [],
            "risks": [],
            "data_quality": "数据质量正常",
        },
    }


class CapitalFlowCalculatorTests(unittest.TestCase):
    def test_flow_price_prefers_same_day_nav(self):
        self.assertEqual(flow_price_for_etf("510300.SH", 4.9, {"510300.SH": 4.8123}), (4.8123, "nav", "净值口径"))

    def test_flow_price_falls_back_to_close_when_nav_missing(self):
        self.assertEqual(flow_price_for_etf("510300.SH", 4.9, {}), (4.9, "close", "收盘价估算"))

    def test_change_pct_from_close_uses_previous_close(self):
        self.assertEqual(round(change_pct_from_close(10.5, 10.0) or 0, 2), 5.0)
        self.assertIsNone(change_pct_from_close(10.5, None))

    def test_hsgt_item_uses_daily_net_amount_in_wan_yuan(self):
        item = hsgt_item("北上资金", [{"north_money": "339321.25"}], "north_money")

        self.assertEqual(item["latest_value_yi"], 33.93)
        self.assertEqual(item["net_change_yi"], 33.93)

    def test_hsgt_item_sums_window_rows(self):
        item = hsgt_item("北上资金", [{"north_money": "10000"}, {"north_money": "-5000"}], "north_money")

        self.assertEqual(item["latest_value_yi"], 0.5)
        self.assertEqual(item["net_change_yi"], 0.5)

    def test_section_payload_can_filter_only_when_requested(self):
        groups = {
            ("broad", "沪深300"): EtfFlowGroup(
                section="broad",
                index_name="沪深300",
                index_code="000300.SH",
                scale_yi=12,
                net_flow_yi=1,
            ),
            ("a_industry", "小行业"): EtfFlowGroup(section="a_industry", index_name="小行业", scale_yi=2, net_flow_yi=1),
            ("a_industry", "大行业"): EtfFlowGroup(section="a_industry", index_name="大行业", scale_yi=12, net_flow_yi=3),
            ("a_industry", "非银金融"): EtfFlowGroup(
                section="a_industry", index_name="非银金融", scale_yi=20, net_flow_yi=2
            ),
            ("a_industry", "电力"): EtfFlowGroup(section="a_industry", index_name="电力", scale_yi=30, net_flow_yi=1.5),
        }

        broad_rows = section_payload(groups, "broad", "宽基ETF净申购金额", min_scale_yi=10)["rows"]
        industry_rows = section_payload(groups, "a_industry", "A股行业净申购金额", min_scale_yi=10)["rows"]

        self.assertEqual([row["index_name"] for row in broad_rows], ["沪深300"])
        self.assertEqual(broad_rows[0]["index_code"], "000300.SH")
        self.assertEqual([row["index_name"] for row in industry_rows], ["大行业", "非银金融", "电力"])
        self.assertEqual(industry_rows[0]["index_code"], "")
        self.assertEqual(industry_rows[1]["display_name"], "证券保险/非银金融")
        self.assertEqual(industry_rows[2]["display_name"], "公用事业/电力")

    def test_group_payload_keeps_internal_debug_etfs_by_flow_contribution(self):
        group = EtfFlowGroup(section="broad", index_name="沪深300", index_code="000300.SH")
        group.top_etfs = [
            {"code": "510300.SH", "scale_yi": 100, "net_flow_yi": 1, "share_change_wan": 100},
            {"code": "159919.SZ", "scale_yi": 20, "net_flow_yi": -3, "share_change_wan": -200},
            {"code": "510310.SH", "scale_yi": 50, "net_flow_yi": 2, "share_change_wan": 150},
        ]

        row = section_payload({("broad", "沪深300"): group}, "broad", "宽基ETF净申购金额", min_scale_yi=None)[
            "rows"
        ][0]

        self.assertEqual([item["code"] for item in row["top_etfs"]], ["510300.SH", "510310.SH", "159919.SZ"])
        self.assertEqual([item["code"] for item in row["debug_etfs"]], ["159919.SZ", "510310.SH", "510300.SH"])
        self.assertEqual(row["debug_etfs"][0]["share_change_wan"], -200)

    def test_etf_flow_reports_target_coverage_and_strategy_section(self):
        funds = {
            "510880.SH": {
                "name": "红利ETF华泰柏瑞",
                "benchmark": "上证红利指数",
                "invest_type": "被动指数型",
            },
            "511880.SH": {
                "name": "银华日利ETF",
                "benchmark": "活期存款利率(税后)",
                "invest_type": "货币型",
            },
            "159999.SZ": {
                "name": "未知权益ETF",
                "benchmark": "未知权益指数",
                "invest_type": "被动指数型",
            },
        }
        payload = etf_flows_for_window(
            funds,
            ["20260611", "20260610"],
            1,
            daily_prices={
                "20260611": {"510880.SH": 2.0, "511880.SH": 100.0, "159999.SZ": 1.0},
                "20260610": {"510880.SH": 1.9, "511880.SH": 100.0, "159999.SZ": 1.0},
            },
            daily_navs={"20260611": {}},
            daily_shares={
                "20260611": {"510880.SH": 110000, "511880.SH": 10000, "159999.SZ": 1000},
                "20260610": {"510880.SH": 10000, "511880.SH": 10000, "159999.SZ": 1000},
            },
        )

        self.assertEqual(payload["coverage"]["priced_etf_count"], 3)
        self.assertEqual(payload["coverage"]["target_equity_etf_count"], 2)
        self.assertEqual(payload["coverage"]["frontend_target_equity_etf_count"], 2)
        self.assertEqual(payload["coverage"]["non_frontend_target_equity_etf_count"], 0)
        self.assertEqual(payload["coverage"]["classified_target_equity_etf_count"], 1)
        self.assertEqual(payload["coverage"]["excluded_non_target_etf_count"], 1)
        self.assertEqual(payload["coverage"]["raw_target_coverage_pct"], 50.0)
        self.assertEqual(payload["coverage"]["target_coverage_pct"], 50.0)
        self.assertEqual(payload["quality"]["nav_count"], 0)
        self.assertEqual(payload["quality"]["close_estimate_count"], 1)
        self.assertEqual(payload["quality"]["skipped_flow_count"], 0)
        self.assertEqual(payload["quality"]["price_source_label"], "收盘价估算")
        self.assertEqual(payload["sections"]["strategy"]["rows"][0]["index_name"], "红利")

    def test_etf_flow_coverage_excludes_enhanced_etfs_from_frontend_denominator(self):
        funds = {
            "510300.SH": {
                "name": "沪深300ETF华泰柏瑞",
                "benchmark": "沪深300指数收益率",
                "invest_type": "被动指数型",
            },
            "159238.SZ": {
                "name": "沪深300增强ETF景顺",
                "benchmark": "沪深300指数收益率",
                "invest_type": "增强指数型",
            },
            "159981.SZ": {
                "name": "能源化工ETF建信",
                "benchmark": "易盛郑商所能源化工指数A",
                "invest_type": "能源化工期货型",
            },
        }
        payload = etf_flows_for_window(
            funds,
            ["20260611", "20260610"],
            1,
            daily_prices={
                "20260611": {"510300.SH": 4.0, "159238.SZ": 1.0, "159981.SZ": 1.0},
                "20260610": {"510300.SH": 3.9, "159238.SZ": 1.0, "159981.SZ": 1.0},
            },
            daily_navs={"20260611": {}},
            daily_shares={
                "20260611": {"510300.SH": 110000, "159238.SZ": 110000, "159981.SZ": 110000},
                "20260610": {"510300.SH": 100000, "159238.SZ": 100000, "159981.SZ": 100000},
            },
        )

        self.assertEqual(payload["coverage"]["priced_etf_count"], 3)
        self.assertEqual(payload["coverage"]["target_equity_etf_count"], 2)
        self.assertEqual(payload["coverage"]["frontend_target_equity_etf_count"], 1)
        self.assertEqual(payload["coverage"]["non_frontend_target_equity_etf_count"], 1)
        self.assertEqual(payload["coverage"]["excluded_non_target_etf_count"], 1)
        self.assertEqual(payload["coverage"]["classified_target_equity_etf_count"], 1)
        self.assertEqual(payload["coverage"]["raw_target_coverage_pct"], 50.0)
        self.assertEqual(payload["coverage"]["target_coverage_pct"], 100.0)
        self.assertEqual(payload["sections"]["broad"]["rows"][0]["index_name"], "沪深300")

    def test_etf_flow_quality_reports_skipped_window_points(self):
        funds = {
            "510300.SH": {
                "name": "沪深300ETF华泰柏瑞",
                "benchmark": "沪深300指数收益率",
                "invest_type": "被动指数型",
            },
        }
        payload = etf_flows_for_window(
            funds,
            ["20260611", "20260610"],
            1,
            daily_prices={
                "20260611": {"510300.SH": 4.0},
                "20260610": {"510300.SH": 3.9},
            },
            daily_navs={"20260611": {}},
            daily_shares={
                "20260611": {"510300.SH": 60000},
                "20260610": {},
            },
        )

        self.assertEqual(payload["quality"]["skipped_flow_count"], 1)
        row = payload["sections"]["broad"]["rows"][0]
        self.assertEqual(row["skipped_flow_count"], 1)
        self.assertEqual(row["debug_etfs"][0]["skipped_flow_count"], 1)

    def test_etf_flow_rows_include_daily_net_flow_series(self):
        funds = {
            "510300.SH": {
                "name": "沪深300ETF华泰柏瑞",
                "benchmark": "沪深300指数收益率",
                "invest_type": "被动指数型",
            },
        }
        payload = etf_flows_for_window(
            funds,
            ["20260611", "20260610", "20260609"],
            2,
            daily_prices={
                "20260611": {"510300.SH": 4.0},
                "20260610": {"510300.SH": 3.9},
                "20260609": {"510300.SH": 3.8},
            },
            daily_navs={"20260611": {}, "20260610": {}},
            daily_shares={
                "20260611": {"510300.SH": 120000},
                "20260610": {"510300.SH": 100000},
                "20260609": {"510300.SH": 90000},
            },
            daily_amounts={
                "20260611": {"510300.SH": 2.0},
                "20260610": {"510300.SH": 1.0},
            },
        )

        row = payload["sections"]["broad"]["rows"][0]
        self.assertEqual(row["net_flow_yi"], 11.9)
        self.assertEqual(row["start_scale_yi"], 34.2)
        self.assertEqual(row["turnover_yi"], 3.0)
        self.assertEqual(row["turnover_ratio"], 4.03)
        self.assertEqual(row["daily_net_flow"], [{"date": "2026-06-10", "value": 3.9}, {"date": "2026-06-11", "value": 8.0}])
        self.assertEqual(row["daily_change_pct"], [{"date": "2026-06-10", "value": 2.63}, {"date": "2026-06-11", "value": 2.56}])
        self.assertEqual(
            row["daily_turnover"],
            [
                {"date": "2026-06-10", "value": 1.0, "start_scale_yi": 34.2},
                {"date": "2026-06-11", "value": 2.0, "start_scale_yi": 39.0},
            ],
        )
        self.assertEqual(
            row["scale_audit"],
            {
                "status": "ok",
                "point_count": 2,
                "scale_delta_yi": 13.8,
                "net_flow_yi": 11.9,
                "market_effect_yi": 1.9,
                "residual_yi": 0.0,
                "residual_ratio_pct": 0.0,
            },
        )
        self.assertEqual(payload["quality"]["flow_price_status"], "estimated")
        self.assertEqual(payload["quality"]["nav_estimate_ratio_pct"], 100.0)
        self.assertEqual(payload["quality"]["scale_audit"]["status"], "ok")

    def test_etf_debug_share_change_uses_window_start_share(self):
        funds = {
            "510300.SH": {
                "name": "沪深300ETF华泰柏瑞",
                "benchmark": "沪深300指数收益率",
                "invest_type": "被动指数型",
            },
        }
        payload = etf_flows_for_window(
            funds,
            ["20260611", "20260610", "20260609"],
            2,
            daily_prices={
                "20260611": {"510300.SH": 4.0},
                "20260610": {"510300.SH": 3.9},
                "20260609": {"510300.SH": 3.8},
            },
            daily_navs={"20260611": {}, "20260610": {}},
            daily_shares={
                "20260611": {"510300.SH": 120000},
                "20260610": {"510300.SH": 100000},
                "20260609": {"510300.SH": 90000},
            },
        )

        debug_item = payload["sections"]["broad"]["rows"][0]["debug_etfs"][0]
        self.assertEqual(debug_item["latest_share_wan"], 120000)
        self.assertEqual(debug_item["previous_share_wan"], 90000)
        self.assertEqual(debug_item["share_change_wan"], 30000)
        self.assertEqual(debug_item["window_start_share_wan"], 90000)
        self.assertEqual(debug_item["window_share_change_wan"], 30000)

    def test_etf_flow_regression_snapshot_for_core_accounting(self):
        funds = {
            "510300.SH": {
                "name": "沪深300ETF华泰柏瑞",
                "benchmark": "沪深300指数收益率",
                "invest_type": "被动指数型",
            },
            "515050.SH": {
                "name": "通信ETF华夏",
                "benchmark": "中证5G通信主题指数收益率",
                "invest_type": "被动指数型",
            },
        }
        payload = etf_flows_for_window(
            funds,
            ["20260611", "20260610", "20260609"],
            2,
            daily_prices={
                "20260611": {"510300.SH": 4.0, "515050.SH": 1.04},
                "20260610": {"510300.SH": 3.9, "515050.SH": 3.06},
                "20260609": {"510300.SH": 3.8, "515050.SH": 3.0},
            },
            daily_navs={"20260611": {}, "20260610": {}},
            daily_shares={
                "20260611": {"510300.SH": 120000, "515050.SH": 304000},
                "20260610": {"510300.SH": 100000, "515050.SH": 303000},
                "20260609": {"510300.SH": 90000, "515050.SH": 100000},
            },
            daily_amounts={
                "20260611": {"510300.SH": 2.0, "515050.SH": 0.8},
                "20260610": {"510300.SH": 1.0, "515050.SH": 0.6},
            },
        )

        self.assertEqual(core_accounting_snapshot(payload), read_fixture("etf_flow_regression_snapshot.json"))

    def test_etf_flow_adjusts_share_split_before_price_adjusts(self):
        funds = {
            "515050.SH": {
                "name": "通信ETF华夏",
                "benchmark": "中证5G通信主题指数收益率",
                "invest_type": "被动指数型",
            },
        }
        payload = etf_flows_for_window(
            funds,
            ["20260611", "20260610", "20260609"],
            2,
            daily_prices={
                "20260611": {"515050.SH": 1.04},
                "20260610": {"515050.SH": 3.06},
                "20260609": {"515050.SH": 3.0},
            },
            daily_navs={"20260611": {}, "20260610": {}},
            daily_shares={
                "20260611": {"515050.SH": 304000},
                "20260610": {"515050.SH": 303000},
                "20260609": {"515050.SH": 100000},
            },
        )

        row = payload["sections"]["a_industry"]["rows"][0]
        self.assertEqual(row["daily_net_flow"], [{"date": "2026-06-10", "value": 0.31}, {"date": "2026-06-11", "value": 0.1}])
        self.assertEqual(row["daily_change_pct"], [{"date": "2026-06-10", "value": 2.0}, {"date": "2026-06-11", "value": 1.96}])
        self.assertEqual(row["net_flow_yi"], 0.41)
        self.assertEqual(row["split_adjusted_count"], 1)
        self.assertEqual(payload["quality"]["split_adjusted_count"], 1)
        self.assertEqual(row["debug_etfs"][0]["flow_price"], 1.02)
        self.assertEqual(row["debug_etfs"][0]["split_adjusted_count"], 1)
        self.assertEqual(row["scale_audit"]["status"], "ok")

    def test_etf_flow_adjusts_reverse_share_split_before_price_adjusts(self):
        funds = {
            "510300.SH": {
                "name": "沪深300ETF华泰柏瑞",
                "benchmark": "沪深300指数收益率",
                "invest_type": "被动指数型",
            },
        }
        payload = etf_flows_for_window(
            funds,
            ["20260611", "20260610", "20260609"],
            2,
            daily_prices={
                "20260611": {"510300.SH": 30.9},
                "20260610": {"510300.SH": 10.2},
                "20260609": {"510300.SH": 10.0},
            },
            daily_navs={"20260611": {}, "20260610": {}},
            daily_shares={
                "20260611": {"510300.SH": 10200},
                "20260610": {"510300.SH": 10100},
                "20260609": {"510300.SH": 30000},
            },
        )

        row = payload["sections"]["broad"]["rows"][0]
        self.assertEqual(row["daily_net_flow"], [{"date": "2026-06-10", "value": 0.31}, {"date": "2026-06-11", "value": 0.31}])
        self.assertEqual(row["daily_change_pct"], [{"date": "2026-06-10", "value": 2.0}, {"date": "2026-06-11", "value": 0.98}])
        self.assertEqual(row["net_flow_yi"], 0.61)
        self.assertEqual(row["split_adjusted_count"], 1)
        self.assertEqual(row["debug_etfs"][0]["flow_price"], 30.6)
        self.assertEqual(row["scale_audit"]["status"], "ok")

    def test_etf_change_pct_uses_adjusted_factor_for_dividend_days(self):
        funds = {
            "510300.SH": {
                "name": "沪深300ETF华泰柏瑞",
                "benchmark": "沪深300指数收益率",
                "invest_type": "被动指数型",
            },
        }
        payload = etf_flows_for_window(
            funds,
            ["20260611", "20260610"],
            1,
            daily_prices={
                "20260611": {"510300.SH": 9.6},
                "20260610": {"510300.SH": 10.0},
            },
            daily_navs={"20260611": {}},
            daily_shares={
                "20260611": {"510300.SH": 101000},
                "20260610": {"510300.SH": 100000},
            },
            daily_adj_factors={
                "20260611": {"510300.SH": 1.05},
                "20260610": {"510300.SH": 1.0},
            },
        )

        row = payload["sections"]["broad"]["rows"][0]
        self.assertEqual(row["change_pct"], 0.8)
        self.assertEqual(row["daily_change_pct"], [{"date": "2026-06-11", "value": 0.8}])
        self.assertEqual(row["net_flow_yi"], 0.96)

    def test_etf_scale_and_flow_ratio_prefer_nav_over_close(self):
        funds = {
            "510300.SH": {
                "name": "沪深300ETF华泰柏瑞",
                "benchmark": "沪深300指数收益率",
                "invest_type": "被动指数型",
            },
        }
        payload = etf_flows_for_window(
            funds,
            ["20260611", "20260610"],
            1,
            daily_prices={
                "20260611": {"510300.SH": 10.0},
                "20260610": {"510300.SH": 8.0},
            },
            daily_navs={
                "20260611": {"510300.SH": 9.5},
                "20260610": {"510300.SH": 8.5},
            },
            daily_shares={
                "20260611": {"510300.SH": 110000},
                "20260610": {"510300.SH": 100000},
            },
        )

        row = payload["sections"]["broad"]["rows"][0]
        self.assertEqual(row["net_flow_yi"], 9.5)
        self.assertEqual(row["scale_yi"], 104.5)
        self.assertEqual(row["start_scale_yi"], 85.0)
        self.assertEqual(row["net_flow_ratio"], 11.18)
        self.assertEqual(row["scale_audit"]["scale_delta_yi"], 30.0)
        self.assertEqual(row["scale_audit"]["residual_yi"], 0.5)

    def test_turnover_ratio_averages_daily_turnover_intensity(self):
        funds = {
            "510300.SH": {
                "name": "沪深300ETF华泰柏瑞",
                "benchmark": "沪深300指数收益率",
                "invest_type": "被动指数型",
            },
        }
        payload = etf_flows_for_window(
            funds,
            ["20260611", "20260610", "20260609"],
            2,
            daily_prices={
                "20260611": {"510300.SH": 10.0},
                "20260610": {"510300.SH": 10.0},
                "20260609": {"510300.SH": 10.0},
            },
            daily_navs={"20260611": {}, "20260610": {}},
            daily_shares={
                "20260611": {"510300.SH": 20000},
                "20260610": {"510300.SH": 10000},
                "20260609": {"510300.SH": 10000},
            },
            daily_amounts={
                "20260611": {"510300.SH": 2.0},
                "20260610": {"510300.SH": 1.0},
            },
        )

        row = payload["sections"]["broad"]["rows"][0]
        self.assertEqual(row["daily_turnover"][0]["start_scale_yi"], 10.0)
        self.assertEqual(row["daily_turnover"][1]["start_scale_yi"], 10.0)
        self.assertEqual(row["turnover_ratio"], 15.0)

    def test_etf_flow_ratio_uses_window_start_scale(self):
        funds = {
            "510300.SH": {
                "name": "沪深300ETF华泰柏瑞",
                "benchmark": "沪深300指数收益率",
                "invest_type": "被动指数型",
            },
        }
        payload = etf_flows_for_window(
            funds,
            ["20260611", "20260610"],
            1,
            daily_prices={
                "20260611": {"510300.SH": 2.0},
                "20260610": {"510300.SH": 1.0},
            },
            daily_navs={"20260611": {}},
            daily_shares={
                "20260611": {"510300.SH": 400000},
                "20260610": {"510300.SH": 200000},
            },
        )

        row = payload["sections"]["broad"]["rows"][0]
        self.assertEqual(row["net_flow_yi"], 40.0)
        self.assertEqual(row["scale_yi"], 80.0)
        self.assertEqual(row["start_scale_yi"], 20.0)
        self.assertEqual(row["net_flow_ratio"], 200.0)


if __name__ == "__main__":
    unittest.main()
