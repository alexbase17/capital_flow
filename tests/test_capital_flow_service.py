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

    def test_classifies_broad_a_share_etfs(self):
        self.assertEqual(
            classify_etf_group("沪深300ETF华泰柏瑞", benchmark="沪深300指数收益率", invest_type="被动指数型"),
            ("broad", "沪深300"),
        )
        self.assertEqual(
            classify_etf_group("A500ETF南方", benchmark="中证A500指数收益率", invest_type="被动指数型"),
            ("broad", "中证A500"),
        )
        self.assertEqual(
            classify_etf_group("深证100ETF易方达", benchmark="深证100价格指数", invest_type="被动指数型"),
            ("broad", "深证100"),
        )
        self.assertEqual(
            classify_etf_group("科创创业50ETF华夏", benchmark="中证科创创业50指数收益率", invest_type="被动指数型"),
            ("broad", "科创创业50"),
        )

    def test_taxonomy_master_data_loads_required_exact_mappings(self):
        records = load_taxonomy_records()

        self.assertGreater(len(records), 100)
        self.assertEqual(records["沪深300指数"].section, "broad")
        self.assertEqual(records["沪深300指数"].index_code, "000300.SH")
        self.assertEqual(records["深证50指数"].index_code, "399850.SZ")
        self.assertEqual(records["国证2000指数"].index_code, "399303.SZ")
        self.assertEqual(records["中证800指数"].index_code, "000906.SH")
        self.assertEqual(records["中小企业100指数"].index_code, "399005.SZ")
        self.assertEqual(records["中证金融科技主题指数"].taxonomy_type, "theme")
        self.assertEqual(records["中证金融科技主题指数"].parent_bucket, "科技")
        self.assertEqual(records["中证全指证券公司指数"].index_code, "h20168.CSI")
        self.assertEqual(records["中证全指通信设备指数"].index_code, "h21160.CSI")
        self.assertEqual(records["中证细分化工产业主题指数"].index_code, "000813.CSI")
        self.assertEqual(records["中证创新药产业指数"].index_code, "931152.CSI")
        self.assertEqual(records["中证银行指数"].index_code, "399986.CSI")
        self.assertIn("恒生港股通汽车主题指数", records)
        self.assertEqual(records["沪深300指数"], EXACT_BENCHMARK_RECORDS["沪深300指数"])

    def test_target_equity_uses_exact_taxonomy_before_broad_exclusion_markers(self):
        self.assertTrue(is_target_equity_etf("标普A股红利ETF华宝", "标普中国A股红利100指数"))
        self.assertTrue(is_target_equity_etf("标普A股红利ETF华宝", "标普中国A股红利机会指数"))
        self.assertTrue(is_target_equity_etf("港股低波红利ETF摩根", "标普港股通低波红利指数"))
        self.assertFalse(is_target_equity_etf("标普500ETF", "标普500指数"))

    def test_etf_flow_excludes_non_target_etfs_even_if_pattern_classifies(self):
        funds = {
            "159529.SZ": {
                "name": "标普消费ETF景顺",
                "benchmark": "标普500消费精选指数收益率(使用估值汇率调整)",
                "invest_type": "被动指数型",
            },
            "562060.SH": {
                "name": "标普A股红利ETF华宝",
                "benchmark": "标普中国A股红利机会指数收益率",
                "invest_type": "被动指数型",
            },
        }
        payload = etf_flows_for_window(
            funds,
            ["20260611", "20260610"],
            1,
            daily_prices={
                "20260611": {"159529.SZ": 1.0, "562060.SH": 1.0},
                "20260610": {"159529.SZ": 1.0, "562060.SH": 1.0},
            },
            daily_navs={"20260611": {}, "20260610": {}},
            daily_shares={
                "20260611": {"159529.SZ": 310000, "562060.SH": 310000},
                "20260610": {"159529.SZ": 300000, "562060.SH": 300000},
            },
        )

        self.assertEqual(payload["coverage"]["target_equity_etf_count"], 1)
        self.assertEqual(payload["coverage"]["classified_target_equity_etf_count"], 1)
        self.assertEqual(payload["coverage"]["excluded_non_target_etf_count"], 1)
        self.assertEqual(payload["sections"]["a_industry"]["rows"], [])
        self.assertEqual(payload["sections"]["strategy"]["rows"][0]["index_name"], "红利")
        self.assertEqual(payload["sections"]["strategy"]["rows"][0]["net_flow_yi"], 1.0)

    def test_index_name_aliases_support_index_basic_matching(self):
        aliases = index_name_aliases("中证人工智能主题")
        self.assertIn("中证人工智能主题", aliases)
        self.assertIn("中证人工智能主题指数", aliases)
        self.assertIn("人工智能", aliases)
        self.assertIn("中证人工智能主题", index_name_aliases("中证人工智能主题指数"))
        self.assertIn("人工智能", index_name_aliases("中证人工智能主题指数"))
        self.assertEqual(canonical_index_name("中证人工智能主题指数"), "人工智能")
        self.assertEqual(index_provider_hint("国证生物医药指数"), "SZSE")

    def test_resolve_index_code_prefers_master_data_then_index_lookup(self):
        records = load_taxonomy_records()

        self.assertEqual(resolve_index_code(records["沪深300指数"], {"沪深300指数": "SHOULD_NOT_USE"}), "000300.SH")
        self.assertEqual(resolve_index_code(records["中证金融科技主题指数"], {"中证金融科技主题指数": "930986.CSI"}), "930986.CSI")

    def test_resolve_index_code_requires_unique_provider_compatible_match(self):
        records = load_taxonomy_records()
        csi_record = records["中证人工智能主题指数"]
        szse_record = records["国证消费电子主题指数"]
        lookup = {
            "canonical:人工智能": [
                {"code": "931071.CSI", "name": "中证人工智能主题指数", "market": "CSI", "publisher": "中证指数有限公司"},
                {"code": "399000.SZ", "name": "国证人工智能指数", "market": "SZSE", "publisher": "深圳证券信息有限公司"},
            ],
            "canonical:消费电子": [
                {"code": "399123.SZ", "name": "国证消费电子主题指数", "market": "SZSE", "publisher": "深圳证券信息有限公司"},
                {"code": "931999.CSI", "name": "中证消费电子指数", "market": "CSI", "publisher": "中证指数有限公司"},
            ],
            "canonical:云计算": [
                {"code": "931470.CSI", "name": "中证云计算与大数据主题指数", "market": "CSI", "publisher": "中证指数有限公司"},
                {"code": "931471.CSI", "name": "中证云计算产业指数", "market": "CSI", "publisher": "中证指数有限公司"},
            ],
        }

        self.assertEqual(resolve_index_code(csi_record, lookup), "931071.CSI")
        self.assertEqual(resolve_index_code(szse_record, lookup), "399123.SZ")
        self.assertEqual(resolve_index_code(records["中证云计算与大数据主题指数"], lookup), "")

    def test_broad_classification_excludes_strategy_variants(self):
        self.assertIsNone(
            classify_etf_group("沪深300增强ETF景顺", benchmark="沪深300指数收益率", invest_type="增强指数型"),
        )
        self.assertEqual(
            classify_etf_group("沪深300价值ETF华夏", benchmark="沪深300价值指数收益率", invest_type="被动指数型"),
            ("strategy", "价值"),
        )
        self.assertEqual(
            classify_etf_group(
                "A500红利低波ETF易方达", benchmark="中证A500红利低波动指数收益率", invest_type="被动指数型"
            ),
            ("strategy", "红利低波"),
        )
        self.assertEqual(
            classify_etf_group("创业板综ETF银华", benchmark="创业板综合指数收益率", invest_type="被动指数型"),
            ("broad", "创业板综"),
        )
        self.assertEqual(
            classify_etf_group("创业板200ETF南方", benchmark="创业板中盘200指数收益率", invest_type="被动指数型"),
            ("broad", "创业板200"),
        )
        self.assertIsNone(
            classify_etf_group("创业板科技ETF华泰柏瑞", benchmark="创业板科技指数收益率", invest_type="被动指数型")
        )
        self.assertIsNone(
            classify_etf_group("创业板大盘ETF招商", benchmark="创业板大盘指数收益率", invest_type="被动指数型")
        )
        self.assertEqual(
            classify_etf_group("中国A50ETF南方", benchmark="MSCI中国A50互联互通指数(人民币)收益率", invest_type="被动指数型"),
            ("broad", "MSCI中国A50"),
        )
        self.assertIsNone(
            classify_etf_group("双创50增强ETF广发", benchmark="中证科创创业50指数收益率", invest_type="增强指数型"),
        )
        self.assertIsNone(
            classify_etf_group("富时A50ETF嘉实", benchmark="富时中国A50指数收益率", invest_type="被动指数型")
        )

    def test_classifies_hk_broad_etfs_by_benchmark(self):
        self.assertEqual(
            classify_etf_group("恒生ETF华夏", benchmark="(人民币/港币汇率*恒生指数)收益率", invest_type="被动指数型"),
            ("broad", "恒生指数"),
        )
        self.assertEqual(
            classify_etf_group("恒指港股通ETF建信", benchmark="恒指港股通指数收益率(经汇率调整)", invest_type="被动指数型"),
            ("broad", "恒指港股通"),
        )
        self.assertEqual(
            classify_etf_group("港股通50ETF华泰柏瑞", benchmark="中证港股通50指数收益率", invest_type="被动指数型"),
            ("broad", "港股通50"),
        )

    def test_hk_technology_is_not_hk_broad(self):
        self.assertEqual(
            classify_etf_group(
                "恒生科技ETF华夏",
                benchmark="恒生科技指数收益率(使用估值汇率折算)",
                invest_type="被动指数型",
            ),
            ("hk_industry", "恒生科技"),
        )

    def test_strategy_factor_classification_uses_benchmark(self):
        self.assertEqual(
            classify_etf_group("红利低波ETF华泰柏瑞", benchmark="中证红利低波动指数收益率", invest_type="被动指数型"),
            ("strategy", "红利低波"),
        )
        self.assertEqual(
            classify_etf_group("红利ETF华泰柏瑞", benchmark="上证红利指数", invest_type="被动指数型"),
            ("strategy", "红利"),
        )
        self.assertEqual(
            classify_etf_group("港股红利低波ETF银华", benchmark="标普港股通低波红利指数收益率", invest_type="被动指数型"),
            ("strategy", "港股红利低波"),
        )

    def test_high_confidence_theme_mappings(self):
        self.assertEqual(
            classify_etf_group("电网设备ETF华夏", benchmark="中证电网设备主题指数收益率", invest_type="被动指数型"),
            ("a_industry", "电网设备"),
        )
        self.assertEqual(
            classify_etf_group("绿色电力ETF嘉实", benchmark="国证绿色电力指数收益率", invest_type="被动指数型"),
            ("a_industry", "绿色电力"),
        )
        self.assertEqual(
            classify_etf_group("金融科技ETF汇添富", benchmark="中证金融科技主题指数收益率", invest_type="被动指数型"),
            ("a_industry", "金融科技"),
        )
        self.assertEqual(
            classify_etf_group("消费电子ETF鹏华", benchmark="国证消费电子主题指数收益率", invest_type="被动指数型"),
            ("a_industry", "消费电子"),
        )
        self.assertEqual(
            classify_etf_group("港股通汽车ETF易方达", benchmark="恒生港股通汽车主题指数收益率", invest_type="被动指数型"),
            ("hk_industry", "港股汽车"),
        )

    def test_additional_broad_mappings_are_explicit(self):
        self.assertEqual(
            classify_etf_group("深证50ETF易方达", benchmark="深证50指数收益率", invest_type="被动指数型"),
            ("broad", "深证50"),
        )
        self.assertEqual(index_code_for_group("broad", "深证50"), "399850.SZ")
        self.assertEqual(
            classify_etf_group("国证2000ETF博时", benchmark="国证2000指数收益率", invest_type="被动指数型"),
            ("broad", "国证2000"),
        )
        self.assertEqual(index_code_for_group("broad", "国证2000"), "399303.SZ")

    def test_classification_does_not_fall_back_to_fund_name_when_benchmark_missing(self):
        self.assertIsNone(classify_etf_group("沪深300ETF华泰柏瑞"))
        self.assertIsNone(classify_etf_group("沪深300增强ETF景顺", invest_type="增强指数型"))

    def test_industry_classification_uses_benchmark(self):
        self.assertEqual(
            classify_etf_group("创业板人工智能ETF华宝", benchmark="中证人工智能主题指数收益率", invest_type="被动指数型"),
            ("a_industry", "人工智能"),
        )
        self.assertIsNone(classify_etf_group("创业板人工智能ETF华宝"))

    def test_classification_detail_marks_exact_and_pattern_confidence(self):
        exact = classify_etf_detail(
            "创业板人工智能ETF华宝",
            benchmark="中证人工智能主题指数收益率",
            invest_type="被动指数型",
        )
        pattern = classify_etf_detail(
            "机器人ETF样本",
            benchmark="中证机器人产业指数收益率",
            invest_type="被动指数型",
        )

        self.assertIsNotNone(exact)
        self.assertEqual(exact.source, "benchmark_exact")
        self.assertEqual(exact.confidence, "high")
        self.assertEqual(exact.taxonomy_type, "theme")
        self.assertEqual(exact.parent_bucket, "科技")
        self.assertIsNotNone(pattern)
        self.assertEqual(pattern.source, "benchmark_pattern")
        self.assertEqual(pattern.confidence, "medium")

    def test_taxonomy_audit_reports_unclassified_and_pattern_samples(self):
        audit = audit_fund_taxonomy(
            {
                "159819.SZ": {
                    "name": "人工智能ETF易方达",
                    "benchmark": "中证人工智能主题指数收益率",
                    "invest_type": "被动指数型",
                },
                "159770.SZ": {
                    "name": "机器人ETF样本",
                    "benchmark": "中证机器人产业指数收益率",
                    "invest_type": "被动指数型",
                },
                "159999.SZ": {
                    "name": "未知主题ETF样本",
                    "benchmark": "未知主题指数收益率",
                    "invest_type": "被动指数型",
                },
                "159238.SZ": {
                    "name": "沪深300增强ETF景顺",
                    "benchmark": "沪深300指数收益率",
                    "invest_type": "增强指数型",
                },
                "511880.SH": {
                    "name": "货币ETF样本",
                    "benchmark": "中证货币基金指数收益率",
                    "invest_type": "被动指数型",
                },
            }
        )

        self.assertEqual(audit["summary"]["total_etf"], 5)
        self.assertEqual(audit["summary"]["excluded_non_target"], 1)
        self.assertEqual(audit["summary"]["target_equity_etf"], 4)
        self.assertEqual(audit["summary"]["frontend_target_equity_etf"], 3)
        self.assertEqual(audit["summary"]["non_frontend_target_equity"], 1)
        self.assertEqual(audit["summary"]["classified_target_equity"], 2)
        self.assertEqual(audit["summary"]["unclassified_target_equity"], 1)
        self.assertEqual(audit["summary"]["coverage_pct"], 66.67)
        self.assertEqual(audit["summary"]["raw_coverage_pct"], 50.0)
        self.assertEqual(audit["by_source"], {"benchmark_exact": 1, "benchmark_pattern": 1})
        self.assertEqual(audit["by_confidence"], {"high": 1, "medium": 1})
        self.assertEqual(audit["by_taxonomy_type"], {"theme": 1})
        self.assertEqual(audit["by_parent_bucket"], {"科技": 1})
        self.assertEqual(audit["unclassified_samples"][0]["code"], "159999.SZ")
        self.assertEqual(audit["non_frontend_target_samples"][0]["code"], "159238.SZ")
        self.assertEqual(audit["pattern_classified_samples"][0]["label"], "机器人")

    def test_sw2021_exposure_aggregates_latest_index_weights(self):
        exposure = sw2021_exposure_from_weight_rows(
            [
                {"trade_date": "20260601", "con_code": "000001.SZ", "weight": 30},
                {"trade_date": "20260601", "con_code": "000002.SZ", "weight": 20},
                {"trade_date": "20260612", "con_code": "000001.SZ", "weight": 35},
                {"trade_date": "20260612", "con_code": "000002.SZ", "weight": 25},
                {"trade_date": "20260612", "con_code": "000003.SZ", "weight": 10},
            ],
            {"000001.SZ": "电子", "000002.SZ": "计算机"},
        )

        self.assertEqual(exposure["weight_date"], "20260612")
        self.assertEqual(exposure["constituent_count"], 3)
        self.assertEqual(exposure["top_industry"], "电子")
        self.assertEqual(exposure["top_industry_weight"], 35.0)
        self.assertEqual(exposure["top3_weight"], 60.0)
        self.assertEqual(exposure["unknown_weight"], 10.0)

    def test_a_share_benchmark_impacts_prioritizes_current_scale(self):
        impacts = a_share_benchmark_impacts(
            {
                "159819.SZ": {
                    "name": "人工智能ETF易方达",
                    "benchmark": "中证人工智能主题指数收益率",
                    "invest_type": "被动指数型",
                },
                "515050.SH": {
                    "name": "通信ETF华夏",
                    "benchmark": "中证5G通信主题指数收益率",
                    "invest_type": "被动指数型",
                },
                "511880.SH": {
                    "name": "货币ETF样本",
                    "benchmark": "中证货币基金指数收益率",
                    "invest_type": "被动指数型",
                },
            },
            {"159819.SZ": 2.0, "515050.SH": 1.0, "511880.SH": 100.0},
            {"159819.SZ": 50000, "515050.SH": 10000, "511880.SH": 100000},
        )

        self.assertEqual(impacts["中证人工智能主题指数"]["scale_yi"], 10.0)
        self.assertEqual(impacts["中证人工智能主题指数"]["etf_count"], 1)
        self.assertEqual(impacts["中证5G通信主题指数"]["scale_yi"], 1.0)
        self.assertNotIn("中证货币基金指数", impacts)

    def test_label_consistency_flags_mixed_top_industries(self):
        audit = label_consistency_audit(
            [
                {
                    "label": "人工智能",
                    "benchmark": "中证人工智能主题指数",
                    "scale_yi": 100,
                    "top_industry": "通信",
                    "top_industry_weight": 39.87,
                    "unknown_weight": 0,
                },
                {
                    "label": "人工智能",
                    "benchmark": "创业板人工智能指数",
                    "scale_yi": 80,
                    "top_industry": "计算机",
                    "top_industry_weight": 55.0,
                    "unknown_weight": 0,
                },
                {
                    "label": "软件服务",
                    "benchmark": "中证软件服务指数",
                    "scale_yi": 20,
                    "top_industry": "计算机",
                    "top_industry_weight": 95.0,
                    "unknown_weight": 0,
                },
                {
                    "label": "软件服务",
                    "benchmark": "创业板软件指数",
                    "scale_yi": 10,
                    "top_industry": "计算机",
                    "top_industry_weight": 93.0,
                    "unknown_weight": 0,
                },
            ],
        )

        self.assertEqual(audit["label_count"], 2)
        self.assertEqual(audit["consistent_multi_index_label_count"], 1)
        self.assertEqual(audit["flagged_label_count"], 1)
        self.assertEqual(audit["flagged_samples"][0]["label"], "人工智能")
        self.assertEqual(audit["flagged_samples"][0]["scale_yi"], 180)

    def test_broad_benchmark_wins_over_issuer_industry_word(self):
        self.assertEqual(
            classify_etf_group("中证500ETF中银证券", benchmark="中证500指数收益率", invest_type="被动指数型"),
            ("broad", "中证500"),
        )

    def test_industry_benchmark_keeps_software_separate_from_computer(self):
        self.assertEqual(
            classify_etf_group("软件ETF嘉实", benchmark="中证软件服务指数收益率", invest_type="被动指数型"),
            ("a_industry", "软件服务"),
        )
        self.assertEqual(
            classify_etf_group("计算机ETF天弘", benchmark="中证计算机主题指数收益率", invest_type="被动指数型"),
            ("a_industry", "计算机"),
        )

    def test_industry_benchmark_keeps_precise_themes(self):
        self.assertEqual(
            classify_etf_group("卫星ETF永赢", benchmark="国证商用卫星通信产业指数收益率", invest_type="被动指数型"),
            ("a_industry", "卫星通信"),
        )
        self.assertEqual(
            classify_etf_group("证券保险ETF鹏华", benchmark="中证800证券保险指数收益率", invest_type="被动指数型"),
            ("a_industry", "证券保险"),
        )

    def test_non_equity_etfs_are_not_industry_classified(self):
        self.assertIsNone(
            classify_etf_group("货币ETF建信", benchmark="中证银行间货币市场指数收益率", invest_type="被动指数型")
        )
        self.assertIsNone(
            classify_etf_group("短融ETF海富通", benchmark="中证短融指数收益率", invest_type="被动指数型")
        )
        self.assertIsNone(
            classify_etf_group("科创债ETF嘉实", benchmark="中证AAA科技创新公司债指数收益率", invest_type="被动指数型")
        )
        self.assertIsNone(
            classify_etf_group("公司债ETF南方", benchmark="上证基准做市公司债指数收益率", invest_type="被动指数型")
        )

    def test_non_bank_financial_index_is_not_bank(self):
        self.assertEqual(
            classify_etf_group(
                "港股通非银ETF广发",
                benchmark="中证港股通非银行金融综合指数收益率(经估值汇率调整)",
                invest_type="被动指数型",
            ),
            ("hk_industry", "港股非银金融"),
        )

    def test_hk_industry_avoids_cross_word_communication_match(self):
        self.assertEqual(
            classify_etf_group(
                "港股通信息技术ETF华宝",
                benchmark="中证港股通信息技术综合指数(港元)收益率",
                invest_type="被动指数型",
            ),
            ("hk_industry", "港股信息技术"),
        )
        self.assertEqual(
            classify_etf_group(
                "港股通互联网ETF富国",
                benchmark="中证港股通互联网指数(港元)收益率",
                invest_type="被动指数型",
            ),
            ("hk_industry", "港股互联网"),
        )
        self.assertEqual(
            classify_etf_group(
                "港股通科技ETF博时",
                benchmark="恒生港股通科技主题指数收益率(经估值汇率调整)",
                invest_type="被动指数型",
            ),
            ("hk_industry", "港股科技"),
        )
        self.assertEqual(
            classify_etf_group(
                "恒生科技ETF广发",
                benchmark="人民币计价的恒生科技指数收益率",
                invest_type="被动指数型",
            ),
            ("hk_industry", "恒生科技"),
        )
        self.assertEqual(
            classify_etf_group(
                "港股科技ETF银华",
                benchmark="恒生港股通中国科技指数收益率(经估值汇率调整)",
                invest_type="被动指数型",
            ),
            ("hk_industry", "港股科技"),
        )

    def test_hang_seng_a_share_index_is_not_hk_exposure(self):
        self.assertEqual(
            classify_etf_group(
                "电网设备ETF国泰",
                benchmark="恒生A股电网设备指数收益率",
                invest_type="被动指数型",
            ),
            ("a_industry", "电网设备"),
        )

    def test_non_equity_theme_is_ignored(self):
        self.assertIsNone(classify_etf_group("黄金ETF华安"))
        self.assertIsNone(
            classify_etf_group("巴西ETF华夏", benchmark="巴西伊博维斯帕指数收益率", invest_type="被动指数型")
        )

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
