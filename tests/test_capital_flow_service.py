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


class CapitalFlowServiceTests(unittest.TestCase):
    def test_dated_fetcher_maps_are_persistently_cached(self):
        class FakeClient:
            def __init__(self):
                self.calls = 0

            def query(self, api_name, params=None, fields=None):
                self.calls += 1
                if api_name != "fund_daily":
                    raise AssertionError(api_name)
                return [{"ts_code": "510300.SH", "close": "4.2"}]

        client = FakeClient()
        with TemporaryDirectory() as tmpdir, patch.object(fetcher, "CACHE_DIR", fetcher.Path(tmpdir)):
            self.assertEqual(fetcher.fund_daily_map(client, "20250102"), {"510300.SH": 4.2})
            self.assertEqual(fetcher.fund_daily_map(client, "20250102"), {"510300.SH": 4.2})

        self.assertEqual(client.calls, 1)

    def test_cache_file_path_preserves_dotted_code_keys(self):
        with TemporaryDirectory() as tmpdir, patch.object(fetcher, "CACHE_DIR", fetcher.Path(tmpdir)):
            sh_path = fetcher.cache_file_path("fund_nav_history/510300.SH_20250101_20250102")
            sz_path = fetcher.cache_file_path("fund_nav_history/510300.SZ_20250101_20250102")

        self.assertNotEqual(sh_path, sz_path)
        self.assertTrue(str(sh_path).endswith("510300.SH_20250101_20250102.json"))
        self.assertTrue(str(sz_path).endswith("510300.SZ_20250101_20250102.json"))

    def test_fund_daily_snapshot_maps_close_and_amount(self):
        test_case = self

        class FakeClient:
            def query(self, api_name, params=None, fields=None):
                test_case.assertEqual(api_name, "fund_daily")
                test_case.assertEqual(fields, "ts_code,trade_date,close,amount")
                return [{"ts_code": "510300.SH", "close": "4.2", "amount": "123456"}]

        with TemporaryDirectory() as tmpdir, patch.object(fetcher, "CACHE_DIR", fetcher.Path(tmpdir)):
            self.assertEqual(
                fetcher.fund_daily_snapshot_map(FakeClient(), "20250102"),
                {"510300.SH": {"close": 4.2, "amount_yi": 1.23456}},
            )

    def test_fund_adj_map_reads_adjustment_factor(self):
        test_case = self

        class FakeClient:
            def query(self, api_name, params=None, fields=None):
                test_case.assertEqual(api_name, "fund_adj")
                test_case.assertEqual(params, {"trade_date": "20250102"})
                test_case.assertEqual(fields, "ts_code,trade_date,adj_factor")
                return [{"ts_code": "510300.SH", "adj_factor": "1.267"}]

        with TemporaryDirectory() as tmpdir, patch.object(fetcher, "CACHE_DIR", fetcher.Path(tmpdir)):
            self.assertEqual(fund_adj_map(FakeClient(), "20250102"), {"510300.SH": 1.267})

    def test_fund_adj_history_map_reads_adjustment_factor_by_code(self):
        test_case = self

        class FakeClient:
            def query(self, api_name, params=None, fields=None):
                test_case.assertEqual(api_name, "fund_adj")
                test_case.assertEqual(
                    params,
                    {"ts_code": "589270.SH", "start_date": "20250101", "end_date": "20250102"},
                )
                test_case.assertEqual(fields, "ts_code,trade_date,adj_factor")
                return [{"ts_code": "589270.SH", "trade_date": "20250102", "adj_factor": "1.0"}]

        with TemporaryDirectory() as tmpdir, patch.object(fetcher, "CACHE_DIR", fetcher.Path(tmpdir)):
            self.assertEqual(
                fund_adj_history_map(FakeClient(), "589270.SH", start_date="20250101", end_date="20250102"),
                {"20250102": 1.0},
            )

    def test_fund_nav_history_map_reads_unit_nav_by_code(self):
        test_case = self

        class FakeClient:
            def query(self, api_name, params=None, fields=None):
                test_case.assertEqual(api_name, "fund_nav")
                test_case.assertEqual(
                    params,
                    {"ts_code": "510300.SH", "start_date": "20250101", "end_date": "20250102"},
                )
                test_case.assertEqual(fields, "ts_code,nav_date,unit_nav")
                return [{"ts_code": "510300.SH", "nav_date": "20250102", "unit_nav": "4.2"}]

        with TemporaryDirectory() as tmpdir, patch.object(fetcher, "CACHE_DIR", fetcher.Path(tmpdir)):
            self.assertEqual(
                fund_nav_history_map(FakeClient(), "510300.SH", start_date="20250101", end_date="20250102"),
                {"20250102": 4.2},
            )

    def test_fill_missing_adj_factors_uses_code_history_for_bulk_gaps(self):
        class FakeClient:
            pass

        daily_adj_factors = {
            "20250103": {"510300.SH": 1.2},
            "20250102": {"510300.SH": 1.1},
            "20250101": {"510300.SH": 1.0},
        }
        client = FakeClient()
        with patch("src.capital_flow.service.fund_adj_history_map") as mock_history:
            mock_history.return_value = {"20250103": 1.0, "20250102": 1.0, "20250101": 1.0}

            fill_missing_adj_factors(
                client,
                daily_adj_factors,
                fund_dates=["20250103", "20250102", "20250101"],
                required_codes={"510300.SH", "589270.SH"},
                daily_prices={
                    "20250103": {"510300.SH": 4.0, "589270.SH": 1.0},
                    "20250102": {"510300.SH": 3.9, "589270.SH": 1.0},
                    "20250101": {"510300.SH": 3.8},
                },
            )

        mock_history.assert_called_once_with(client, "589270.SH", start_date="20250101", end_date="20250103")
        self.assertEqual(daily_adj_factors["20250103"]["589270.SH"], 1.0)
        self.assertEqual(daily_adj_factors["20250102"]["589270.SH"], 1.0)
        self.assertNotIn("589270.SH", daily_adj_factors["20250101"])

    def test_fill_missing_navs_uses_code_history_for_bulk_gaps(self):
        class FakeClient:
            pass

        daily_navs = {
            "20250103": {"510300.SH": 4.1},
            "20250102": {"510300.SH": 4.0},
            "20250101": {"510300.SH": 3.9},
        }
        client = FakeClient()
        with patch("src.capital_flow.service.fund_nav_history_map") as mock_history:
            mock_history.return_value = {"20250103": 1.0, "20250102": 1.1, "20250101": 1.2}

            backfilled_count = fill_missing_navs(
                client,
                daily_navs,
                fund_dates=["20250103", "20250102", "20250101"],
                required_codes={"510300.SH", "589270.SH"},
                daily_prices={
                    "20250103": {"510300.SH": 4.0, "589270.SH": 1.0},
                    "20250102": {"510300.SH": 3.9, "589270.SH": 1.0},
                    "20250101": {"510300.SH": 3.8},
                },
            )

        mock_history.assert_called_once_with(client, "589270.SH", start_date="20250101", end_date="20250103")
        self.assertEqual(backfilled_count, 2)
        self.assertEqual(daily_navs["20250103"]["589270.SH"], 1.0)
        self.assertEqual(daily_navs["20250102"]["589270.SH"], 1.1)
        self.assertNotIn("589270.SH", daily_navs["20250101"])

    def test_fill_missing_navs_tolerates_history_rate_limit(self):
        daily_navs = {"20250103": {}, "20250102": {}}
        with patch("src.capital_flow.service.fund_nav_history_map", side_effect=TushareUnavailable("rate limit")):
            backfilled_count = fill_missing_navs(
                object(),
                daily_navs,
                fund_dates=["20250103", "20250102"],
                required_codes={"510300.SH"},
                daily_prices={"20250103": {"510300.SH": 4.0}, "20250102": {"510300.SH": 3.9}},
            )

        self.assertEqual(backfilled_count, 0)
        self.assertEqual(daily_navs, {"20250103": {}, "20250102": {}})

    def test_fill_missing_adj_factors_tolerates_history_rate_limit(self):
        daily_adj_factors = {"20250103": {}, "20250102": {}}
        with patch("src.capital_flow.service.fund_adj_history_map", side_effect=TushareUnavailable("rate limit")):
            fill_missing_adj_factors(
                object(),
                daily_adj_factors,
                fund_dates=["20250103", "20250102"],
                required_codes={"510300.SH"},
                daily_prices={"20250103": {"510300.SH": 4.0}, "20250102": {"510300.SH": 3.9}},
            )

        self.assertEqual(daily_adj_factors, {"20250103": {}, "20250102": {}})

    def test_fetcher_cache_can_be_disabled_for_diagnostics(self):
        class FakeClient:
            def __init__(self):
                self.calls = 0

            def query(self, api_name, params=None, fields=None):
                self.calls += 1
                return [{"ts_code": "510300.SH", "close": str(4 + self.calls)}]

        client = FakeClient()
        with (
            TemporaryDirectory() as tmpdir,
            patch.object(fetcher, "CACHE_DIR", fetcher.Path(tmpdir)),
            patch.dict(fetcher.os.environ, {"CAPITAL_FLOW_DISABLE_FILE_CACHE": "1"}),
        ):
            self.assertEqual(fetcher.fund_daily_map(client, "20250102"), {"510300.SH": 5.0})
            self.assertEqual(fetcher.fund_daily_map(client, "20250102"), {"510300.SH": 6.0})

        self.assertEqual(client.calls, 2)

    def test_capital_flow_payload_uses_stale_payload_cache_when_refresh_fails(self):
        payload = minimal_valid_capital_flow_payload("5d")
        with (
            TemporaryDirectory() as tmpdir,
            patch.object(fetcher, "CACHE_DIR", fetcher.Path(tmpdir)),
            patch("src.capital_flow.service._build_capital_flow_payload", side_effect=RuntimeError("fund_nav rate limit")),
        ):
            service._CACHE["payloads"].clear()
            service.write_payload_cache("5d", payload)

            result = service.capital_flow_payload(force_refresh=True, client=object(), window_key="5d")

        self.assertEqual(result["data_status"]["etf"]["payload_cache_status"], "stale")
        self.assertEqual(result["etf"]["data_status"]["payload_cache_status"], "stale")
        self.assertEqual(result["window_payloads"]["5d"]["etf"]["data_status"]["payload_cache_status"], "stale")
        self.assertIn("fund_nav rate limit", result["data_status"]["etf"]["payload_cache_error"])
        self.assertIn("fund_nav rate limit", result["window_payloads"]["5d"]["etf"]["data_status"]["payload_cache_error"])
        self.assertIn("上次成功生成", result["notes"][0])

    def test_capital_flow_payload_uses_recent_disk_payload_on_warm_start(self):
        payload = minimal_valid_capital_flow_payload("5d")
        with (
            TemporaryDirectory() as tmpdir,
            patch.object(fetcher, "CACHE_DIR", fetcher.Path(tmpdir)),
            patch("src.capital_flow.service._build_capital_flow_payload") as build_payload,
        ):
            service._CACHE["payloads"].clear()
            service.write_payload_cache("5d", payload)

            result = service.capital_flow_payload(force_refresh=False, client=object(), window_key="5d")

        build_payload.assert_not_called()
        self.assertEqual(result["data_status"]["etf"]["payload_cache_status"], "stale")
        self.assertEqual(result["etf"]["data_status"]["payload_cache_status"], "stale")
        self.assertEqual(result["window_payloads"]["5d"]["etf"]["data_status"]["payload_cache_status"], "stale")
        self.assertEqual(result["data_status"]["etf"]["payload_cache_error"], "service warm start")

    def test_aligned_fund_dates_uses_latest_complete_price_share_date(self):
        dates, status = aligned_fund_dates(
            ["20260612", "20260611", "20260610"],
            {
                "20260612": {"510300.SH": 4.1},
                "20260611": {"510300.SH": 4.0},
                "20260610": {"510300.SH": 3.9},
            },
            {
                "20260612": {},
                "20260611": {"510300.SH": 10000},
                "20260610": {"510300.SH": 9000},
            },
            2,
        )

        self.assertEqual(dates, ["20260611", "20260610"])
        self.assertEqual(status["status"], "fallback")
        self.assertEqual(status["requested_latest_date"], "2026-06-12")
        self.assertEqual(status["as_of_date"], "2026-06-11")
        self.assertEqual(status["price_date"], "2026-06-11")
        self.assertEqual(status["share_date"], "2026-06-11")
        self.assertTrue(status["is_aligned"])

    def test_aligned_fund_dates_requires_all_target_etfs_on_as_of_date(self):
        dates, status = aligned_fund_dates(
            ["20260612", "20260611", "20260610"],
            {
                "20260612": {"510300.SH": 4.1},
                "20260611": {"510300.SH": 4.0, "510500.SH": 6.0},
                "20260610": {"510300.SH": 3.9},
            },
            {
                "20260612": {"510300.SH": 10000, "510500.SH": 8000},
                "20260611": {"510300.SH": 9900, "510500.SH": 7900},
                "20260610": {"510300.SH": 9800},
            },
            2,
            required_codes={"510300.SH", "510500.SH"},
        )

        self.assertEqual(dates, ["20260611", "20260610"])
        self.assertEqual(status["status"], "fallback")
        self.assertEqual(status["as_of_date"], "2026-06-11")
        self.assertEqual(status["required_etf_count"], 2)
        self.assertEqual(status["missing_price_count"], 1)
        self.assertEqual(status["missing_share_count"], 0)
        self.assertIn("100% 对齐", status["fallback_reason"])

    def test_active_target_etf_codes_uses_latest_price_share_union(self):
        funds = {
            "510300.SH": {"name": "沪深300ETF华泰柏瑞", "benchmark": "沪深300指数收益率"},
            "510500.SH": {"name": "中证500ETF南方", "benchmark": "中证500指数收益率"},
            "159001.SZ": {"name": "货币ETF", "benchmark": "中证货币基金指数收益率"},
            "588000.SH": {"name": "科创50ETF华夏", "benchmark": "上证科创板50成份指数收益率"},
        }

        self.assertEqual(
            active_target_etf_codes(
                funds,
                {"20260612": {"510300.SH": 4.1, "159001.SZ": 1.0, "588000.SH": 1.2}},
                {
                    "20260612": {"510500.SH": 5.2, "159001.SZ": 1.0},
                    "20260611": {"510300.SH": 4.0, "159001.SZ": 1.0},
                },
                ["20260612", "20260611"],
            ),
            {"510300.SH", "510500.SH"},
        )

    def test_aligned_fund_dates_rejects_insufficient_complete_window(self):
        with self.assertRaisesRegex(RuntimeError, "price/share data are not aligned"):
            aligned_fund_dates(
                ["20260612", "20260611"],
                {"20260612": {"510300.SH": 4.1}, "20260611": {"510300.SH": 4.0}},
                {"20260612": {}, "20260611": {"510300.SH": 10000}},
                2,
            )

    def test_capital_flow_schema_rejects_missing_contract_key(self):
        payload = {
            "data_status": {"etf": {}, "north_south": {}},
            "north_south": {"latest_date": "2026-06-11", "previous_date": "2026-06-10", "rows": []},
            "etf": {
                "latest_date": "2026-06-11",
                "previous_date": "2026-06-10",
                "nav_date": "2026-06-11",
                "data_status": {
                    "status": "ready",
                    "as_of_date": "2026-06-11",
                    "price_date": "2026-06-11",
                    "share_date": "2026-06-11",
                    "nav_date": "2026-06-11",
                    "is_aligned": True,
                },
                "coverage": {},
                "quality": {},
                "sections": {
                    "broad": {"title": "宽基", "rows": []},
                    "strategy": {"title": "策略", "rows": []},
                    "a_industry": {"title": "A股", "rows": []},
                    "hk_industry": {"title": "港股", "rows": []},
                },
            },
            "windows": {},
            "default_window": "1d",
            "selected_window": "1d",
            "selected_window_label": "1日",
            "window_payloads": {
                "1d": {
                    "north_south": {"latest_date": "2026-06-11", "previous_date": "2026-06-11", "rows": []},
                    "etf": {
                        "data_status": {
                            "status": "ready",
                            "as_of_date": "2026-06-11",
                            "price_date": "2026-06-11",
                            "share_date": "2026-06-11",
                            "nav_date": "2026-06-11",
                            "is_aligned": True,
                        },
                        "sections": {
                            "broad": {"title": "宽基", "rows": []},
                            "strategy": {"title": "策略", "rows": []},
                            "a_industry": {"title": "A股", "rows": []},
                            "hk_industry": {"title": "港股", "rows": []},
                        }
                    },
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

        self.assertIs(validate_capital_flow_payload(payload), payload)
        del payload["etf"]["sections"]["broad"]

        with self.assertRaisesRegex(ValueError, "sections missing keys"):
            validate_capital_flow_payload(payload)


if __name__ == "__main__":
    unittest.main()
