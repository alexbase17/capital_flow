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


class CapitalFlowTaxonomyTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
