import unittest

from src.capital_flow.service import (
    EtfFlowGroup,
    _change_pct,
    _etf_flows_for_window,
    _flow_price_for_etf,
    _hsgt_item,
    _section_payload,
)
from src.capital_flow.schema import validate_capital_flow_payload
from src.capital_flow.taxonomy import classify_etf_group


class CapitalFlowServiceTests(unittest.TestCase):
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
        self.assertIsNone(
            classify_etf_group("创业板综ETF银华", benchmark="创业板综合指数收益率", invest_type="被动指数型")
        )
        self.assertIsNone(
            classify_etf_group("创业板200ETF南方", benchmark="创业板中盘200指数收益率", invest_type="被动指数型")
        )
        self.assertIsNone(
            classify_etf_group("创业板科技ETF华泰柏瑞", benchmark="创业板科技指数收益率", invest_type="被动指数型")
        )
        self.assertIsNone(
            classify_etf_group("创业板大盘ETF招商", benchmark="创业板大盘指数收益率", invest_type="被动指数型")
        )
        self.assertIsNone(
            classify_etf_group("中国A50ETF南方", benchmark="MSCI中国A50互联互通指数(人民币)收益率", invest_type="被动指数型")
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

    def test_classification_does_not_fall_back_to_fund_name_when_benchmark_missing(self):
        self.assertIsNone(classify_etf_group("沪深300ETF华泰柏瑞"))
        self.assertIsNone(classify_etf_group("沪深300增强ETF景顺", invest_type="增强指数型"))

    def test_industry_classification_uses_benchmark(self):
        self.assertEqual(
            classify_etf_group("创业板人工智能ETF华宝", benchmark="中证人工智能主题指数收益率", invest_type="被动指数型"),
            ("a_industry", "人工智能"),
        )
        self.assertIsNone(classify_etf_group("创业板人工智能ETF华宝"))

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

    def test_flow_price_prefers_same_day_nav(self):
        self.assertEqual(_flow_price_for_etf("510300.SH", 4.9, {"510300.SH": 4.8123}), (4.8123, "nav", "净值口径"))

    def test_flow_price_falls_back_to_close_when_nav_missing(self):
        self.assertEqual(_flow_price_for_etf("510300.SH", 4.9, {}), (4.9, "close", "收盘价估算"))

    def test_change_pct_uses_previous_close(self):
        self.assertEqual(round(_change_pct(10.5, 10.0) or 0, 2), 5.0)
        self.assertIsNone(_change_pct(10.5, None))

    def test_hsgt_item_uses_daily_net_amount_in_wan_yuan(self):
        item = _hsgt_item("北上资金", [{"north_money": "339321.25"}], "north_money")

        self.assertEqual(item["latest_value_yi"], 33.93)
        self.assertEqual(item["net_change_yi"], 33.93)

    def test_hsgt_item_sums_window_rows(self):
        item = _hsgt_item("北上资金", [{"north_money": "10000"}, {"north_money": "-5000"}], "north_money")

        self.assertEqual(item["latest_value_yi"], 0.5)
        self.assertEqual(item["net_change_yi"], 0.5)

    def test_section_payload_can_filter_only_when_requested(self):
        groups = {
            ("broad", "沪深300"): EtfFlowGroup(
                section="broad",
                index_name="沪深300",
                index_code="000300.SH",
                scale_yi=2,
                net_flow_yi=1,
            ),
            ("a_industry", "小行业"): EtfFlowGroup(section="a_industry", index_name="小行业", scale_yi=2, net_flow_yi=1),
            ("a_industry", "大行业"): EtfFlowGroup(section="a_industry", index_name="大行业", scale_yi=12, net_flow_yi=3),
            ("a_industry", "非银金融"): EtfFlowGroup(
                section="a_industry", index_name="非银金融", scale_yi=20, net_flow_yi=2
            ),
            ("a_industry", "电力"): EtfFlowGroup(section="a_industry", index_name="电力", scale_yi=30, net_flow_yi=1.5),
        }

        broad_rows = _section_payload(groups, "broad", "宽基ETF净申购金额", min_scale_yi=None)["rows"]
        industry_rows = _section_payload(groups, "a_industry", "A股行业净申购金额", min_scale_yi=10)["rows"]

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

        row = _section_payload({("broad", "沪深300"): group}, "broad", "宽基ETF净申购金额", min_scale_yi=None)[
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
        payload = _etf_flows_for_window(
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
        self.assertEqual(payload["coverage"]["classified_target_equity_etf_count"], 1)
        self.assertEqual(payload["coverage"]["excluded_non_target_etf_count"], 1)
        self.assertEqual(payload["coverage"]["target_coverage_pct"], 50.0)
        self.assertEqual(payload["quality"]["nav_count"], 0)
        self.assertEqual(payload["quality"]["close_estimate_count"], 1)
        self.assertEqual(payload["quality"]["skipped_flow_count"], 0)
        self.assertEqual(payload["quality"]["price_source_label"], "收盘价估算")
        self.assertEqual(payload["sections"]["strategy"]["rows"][0]["index_name"], "红利")

    def test_etf_flow_quality_reports_skipped_window_points(self):
        funds = {
            "510300.SH": {
                "name": "沪深300ETF华泰柏瑞",
                "benchmark": "沪深300指数收益率",
                "invest_type": "被动指数型",
            },
        }
        payload = _etf_flows_for_window(
            funds,
            ["20260611", "20260610"],
            1,
            daily_prices={
                "20260611": {"510300.SH": 4.0},
                "20260610": {"510300.SH": 3.9},
            },
            daily_navs={"20260611": {}},
            daily_shares={
                "20260611": {"510300.SH": 10000},
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
        payload = _etf_flows_for_window(
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
                "20260611": {"510300.SH": 12000},
                "20260610": {"510300.SH": 10000},
                "20260609": {"510300.SH": 9000},
            },
        )

        row = payload["sections"]["broad"]["rows"][0]
        self.assertEqual(row["net_flow_yi"], 1.19)
        self.assertEqual(row["daily_net_flow"], [{"date": "2026-06-10", "value": 0.39}, {"date": "2026-06-11", "value": 0.8}])

    def test_capital_flow_schema_rejects_missing_contract_key(self):
        payload = {
            "north_south": {"latest_date": "2026-06-11", "previous_date": "2026-06-10", "rows": []},
            "etf": {
                "latest_date": "2026-06-11",
                "previous_date": "2026-06-10",
                "nav_date": "2026-06-11",
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
        }

        self.assertIs(validate_capital_flow_payload(payload), payload)
        del payload["etf"]["sections"]["broad"]

        with self.assertRaisesRegex(ValueError, "sections missing keys"):
            validate_capital_flow_payload(payload)


if __name__ == "__main__":
    unittest.main()
