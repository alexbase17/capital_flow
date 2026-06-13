import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.capital_flow import ai_summary, fetcher
from src.capital_flow.ai_summary import (
    DEFAULT_DEEPSEEK_TIMEOUT_SECONDS,
    DEFAULT_DEEPSEEK_MODEL,
    build_ai_summary_input,
    capital_flow_ai_summary,
    deepseek_timeout_seconds,
    parse_model_json,
    request_deepseek_summary,
    rule_based_summary,
)


def sample_payload():
    daily_change_by_window = {
        "1d": [{"date": "2026-06-12", "value": 1.2}],
        "5d": [
            {"date": "2026-06-08", "value": 1.0},
            {"date": "2026-06-09", "value": -0.5},
            {"date": "2026-06-10", "value": 0.8},
            {"date": "2026-06-11", "value": 0.4},
            {"date": "2026-06-12", "value": 1.2},
        ],
        "20d": [{"date": "2026-06-12", "value": 0.2}],
        "60d": [{"date": "2026-06-12", "value": -2.0}],
    }
    daily_turnover_by_window = {
        key: [{"date": "2026-06-12", "value": 6.2, "start_scale_yi": 100}]
        for key in ("1d", "5d", "20d", "60d")
    }
    row_base = {
        "display_name": "通信",
        "index_name": "通信",
        "index_code": "",
        "change_pct": 1.2,
        "net_flow_yi": 0,
        "net_flow_ratio": 0,
        "turnover_yi": 0,
        "turnover_ratio": 6.2,
        "scale_yi": 120,
        "start_scale_yi": 100,
        "etf_count": 2,
        "nav_count": 2,
        "close_estimate_count": 0,
        "skipped_flow_count": 0,
        "split_adjusted_count": 0,
        "price_source_label": "净值口径",
        "daily_net_flow": [],
        "daily_change_pct": [],
        "daily_turnover": [],
        "scale_audit": {"status": "ok"},
        "top_etfs": [],
        "debug_etfs": [],
    }
    windows = {
        "1d": {
            **row_base,
            "net_flow_yi": 8,
            "net_flow_ratio": 2,
            "change_pct": 1.2,
            "daily_change_pct": daily_change_by_window["1d"],
            "daily_turnover": daily_turnover_by_window["1d"],
        },
        "5d": {
            **row_base,
            "net_flow_yi": 30,
            "net_flow_ratio": 8,
            "turnover_ratio": 6.2,
            "daily_change_pct": daily_change_by_window["5d"],
            "daily_turnover": daily_turnover_by_window["5d"],
        },
        "20d": {
            **row_base,
            "net_flow_yi": 80,
            "net_flow_ratio": 18,
            "daily_change_pct": daily_change_by_window["20d"],
            "daily_turnover": daily_turnover_by_window["20d"],
        },
        "60d": {
            **row_base,
            "net_flow_yi": 120,
            "net_flow_ratio": 35,
            "daily_change_pct": daily_change_by_window["60d"],
            "daily_turnover": daily_turnover_by_window["60d"],
        },
    }
    window_payloads = {}
    for key, row in windows.items():
        window_payloads[key] = {
            "north_south": {"rows": [{"name": "北上资金", "net_change_yi": 10}]},
            "etf": {
                "data_status": {"status": "ready"},
                "quality": {
                    "nav_estimate_ratio_pct": 0.0,
                    "skipped_flow_count": 0,
                    "split_adjusted_count": 0,
                    "scale_audit": {"status": "ok"},
                },
                "sections": {
                    "broad": {"title": "宽基", "rows": []},
                    "a_industry": {"title": "A股", "rows": [row]},
                    "hk_industry": {"title": "港股", "rows": []},
                    "strategy": {"title": "策略", "rows": []},
                },
            },
        }
    return {
        "etf": {
            "latest_date": "2026-06-12",
            "data_status": {
                "price_date": "2026-06-12",
                "share_date": "2026-06-12",
                "nav_date": "2026-06-12",
                "required_etf_count": 100,
                "nav_backfilled_count": 10,
            },
            "coverage": {"target_coverage_pct": 80},
            "quality": {
                "nav_estimate_ratio_pct": 0.0,
                "skipped_flow_count": 0,
                "split_adjusted_count": 0,
                "scale_audit": {"status": "ok"},
            },
        },
        "window_payloads": window_payloads,
    }


class CapitalFlowAiSummaryTests(unittest.TestCase):
    def setUp(self):
        ai_summary._AI_SUMMARY_CACHE.clear()

    def test_build_ai_summary_input_includes_compact_signals(self):
        summary_input = build_ai_summary_input(sample_payload())

        self.assertEqual(summary_input["as_of_date"], "2026-06-12")
        self.assertEqual(summary_input["quality"]["scale_audit"]["status"], "ok")
        self.assertIn("same_window_rule", summary_input["metric_notes"])
        self.assertEqual(summary_input["signals"][0]["name"], "通信")
        self.assertIn("连续流入", summary_input["signals"][0]["tags"])
        self.assertEqual(summary_input["signals"][0]["flow_60d_yi"], 120.0)
        self.assertEqual(summary_input["signals"][0]["change_1d_pct"], 1.2)
        self.assertNotEqual(summary_input["signals"][0]["change_60d_pct"], summary_input["signals"][0]["change_1d_pct"])
        self.assertEqual(summary_input["signals"][0]["turnover_60d_avg_pct"], 6.2)

    def test_build_ai_summary_input_uses_long_window_quality(self):
        payload = sample_payload()
        payload["etf"]["quality"]["nav_estimate_ratio_pct"] = 12.0
        payload["window_payloads"]["60d"]["etf"]["quality"] = {
            "nav_estimate_ratio_pct": 0.0,
            "skipped_flow_count": 3,
            "split_adjusted_count": 1,
            "scale_audit": {"status": "ok"},
        }
        payload["window_payloads"]["60d"]["etf"]["data_status"] = payload["etf"]["data_status"]

        summary_input = build_ai_summary_input(payload)

        self.assertEqual(summary_input["quality"]["nav_estimate_ratio_pct"], 0.0)
        self.assertEqual(summary_input["quality"]["skipped_flow_count"], 3)

    def test_rule_based_summary_is_display_ready(self):
        summary = rule_based_summary(build_ai_summary_input(sample_payload()))

        self.assertEqual(summary["source"], "rules")
        self.assertIn("通信", summary["headline"])
        self.assertGreaterEqual(len(summary["focus_items"]), 1)
        self.assertIn("近5日净申购", summary["focus_items"][0]["detail"])
        self.assertNotIn("tags", summary["focus_items"][0])
        self.assertIn("NAV估算占比", summary["data_quality"])

    def test_capital_flow_ai_summary_skips_network_without_key(self):
        with patch("src.capital_flow.ai_summary.get_config", return_value=None), patch(
            "src.capital_flow.ai_summary.request_json"
        ) as request:
            summary = capital_flow_ai_summary(sample_payload())

        self.assertEqual(summary["status"], "hidden")
        self.assertEqual(summary["source"], "none")
        self.assertEqual(summary["headline"], "")
        self.assertEqual(summary["focus_items"], [])
        request.assert_not_called()

    def test_capital_flow_ai_summary_can_force_hidden_for_main_payload(self):
        with patch("src.capital_flow.ai_summary.get_config", return_value="key"), patch(
            "src.capital_flow.ai_summary.request_json"
        ) as request:
            summary = capital_flow_ai_summary(sample_payload(), use_deepseek=False)

        self.assertEqual(summary["source"], "none")
        self.assertEqual(summary["status"], "hidden")
        request.assert_not_called()

    def test_default_deepseek_model_uses_current_v4_flash(self):
        self.assertEqual(DEFAULT_DEEPSEEK_MODEL, "deepseek-v4-flash")

    def test_default_deepseek_timeout_allows_separate_ai_request(self):
        self.assertEqual(DEFAULT_DEEPSEEK_TIMEOUT_SECONDS, 30)

    def test_deepseek_timeout_seconds_is_clamped(self):
        with patch("src.capital_flow.ai_summary.get_config", return_value="120"):
            self.assertEqual(deepseek_timeout_seconds(), 60)
        with patch("src.capital_flow.ai_summary.get_config", return_value="1"):
            self.assertEqual(deepseek_timeout_seconds(), 5)
        with patch("src.capital_flow.ai_summary.get_config", return_value="bad"):
            self.assertEqual(deepseek_timeout_seconds(), DEFAULT_DEEPSEEK_TIMEOUT_SECONDS)

    def test_capital_flow_ai_summary_hides_when_deepseek_fails(self):
        def fake_config(name, default=None):
            if name == "DEEPSEEK_API_KEY":
                return "key"
            return default

        with patch("src.capital_flow.ai_summary.get_config", side_effect=fake_config), patch(
            "src.capital_flow.ai_summary.request_json", side_effect=TimeoutError("timeout")
        ):
            summary = capital_flow_ai_summary(sample_payload())

        self.assertEqual(summary["status"], "unavailable")
        self.assertEqual(summary["source"], "none")
        self.assertEqual(summary["headline"], "")
        self.assertIn("error", summary)

    def test_capital_flow_ai_summary_reuses_cached_deepseek_result(self):
        def fake_config(name, default=None):
            if name == "DEEPSEEK_API_KEY":
                return "key"
            return default

        response = {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"headline":"关注通信","focus_items":[{"title":"通信流入",'
                            '"detail":"近5日净申购较强。"}],"risks":[],"data_quality":""}'
                        )
                    }
                }
            ]
        }
        with (
            TemporaryDirectory() as tmpdir,
            patch.object(fetcher, "CACHE_DIR", Path(tmpdir)),
            patch("src.capital_flow.ai_summary.get_config", side_effect=fake_config),
            patch("src.capital_flow.ai_summary.request_json", return_value=response) as request,
        ):
            first = capital_flow_ai_summary(sample_payload())
            second = capital_flow_ai_summary(sample_payload())
            ai_summary._AI_SUMMARY_CACHE.clear()
            third = capital_flow_ai_summary(sample_payload())

        self.assertEqual(first["headline"], "关注通信")
        self.assertEqual(second["headline"], "关注通信")
        self.assertEqual(third["headline"], "关注通信")
        self.assertEqual(first["model"], DEFAULT_DEEPSEEK_MODEL)
        request.assert_called_once()

    def test_capital_flow_ai_summary_can_bypass_cached_result(self):
        def fake_config(name, default=None):
            if name == "DEEPSEEK_API_KEY":
                return "key"
            return default

        response = {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"headline":"关注通信","focus_items":[{"title":"通信流入",'
                            '"detail":"近5日净申购较强。"}],"risks":[],"data_quality":""}'
                        )
                    }
                }
            ]
        }
        with (
            TemporaryDirectory() as tmpdir,
            patch.object(fetcher, "CACHE_DIR", Path(tmpdir)),
            patch("src.capital_flow.ai_summary.get_config", side_effect=fake_config),
            patch("src.capital_flow.ai_summary.request_json", return_value=response) as request,
        ):
            capital_flow_ai_summary(sample_payload())
            capital_flow_ai_summary(sample_payload(), use_cache=False)

        self.assertEqual(request.call_count, 2)

    def test_capital_flow_ai_summary_cache_invalidates_when_input_changes(self):
        def fake_config(name, default=None):
            if name == "DEEPSEEK_API_KEY":
                return "key"
            return default

        response = {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"headline":"关注通信","focus_items":[{"title":"通信流入",'
                            '"detail":"近5日净申购较强。"}],"risks":[],"data_quality":""}'
                        )
                    }
                }
            ]
        }
        changed_payload = sample_payload()
        changed_payload["window_payloads"]["5d"]["etf"]["sections"]["a_industry"]["rows"][0]["net_flow_yi"] = 31
        with (
            TemporaryDirectory() as tmpdir,
            patch.object(fetcher, "CACHE_DIR", Path(tmpdir)),
            patch("src.capital_flow.ai_summary.get_config", side_effect=fake_config),
            patch("src.capital_flow.ai_summary.request_json", return_value=response) as request,
        ):
            capital_flow_ai_summary(sample_payload())
            capital_flow_ai_summary(changed_payload)

        self.assertEqual(request.call_count, 2)

    def test_parse_model_json_accepts_fenced_json(self):
        parsed = parse_model_json('```json\n{"headline":"关注通信","focus_items":[]}\n```')

        self.assertEqual(parsed["headline"], "关注通信")

    def test_request_deepseek_summary_normalizes_model_output(self):
        response = {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"headline":"关注通信","focus_items":[{"title":"通信流入",'
                            '"detail":"近5日净申购较强，价格和成交同步确认。","tags":["共振"]}],'
                            '"risks":["注意短历史"],"data_quality":"数据质量较好"}'
                        )
                    }
                }
            ]
        }
        with patch("src.capital_flow.ai_summary.request_json", return_value=response) as request:
            summary = request_deepseek_summary(
                build_ai_summary_input(sample_payload()),
                api_key="key",
                model=DEFAULT_DEEPSEEK_MODEL,
                api_url="https://api.deepseek.com/chat/completions",
            )

        self.assertEqual(summary["headline"], "关注通信")
        self.assertEqual(summary["focus_items"][0]["detail"], "近5日净申购较强，价格和成交同步确认。")
        self.assertNotIn("tags", summary["focus_items"][0])
        sent_payload = request.call_args.kwargs["payload"]
        self.assertEqual(sent_payload["response_format"], {"type": "json_object"})
        self.assertEqual(sent_payload["thinking"], {"type": "disabled"})
        self.assertEqual(sent_payload["max_tokens"], 1200)
        self.assertIn("json_example", sent_payload["messages"][1]["content"])
        self.assertIn("辅助后续观察决策", sent_payload["messages"][1]["content"])
        self.assertIn("任务目标", sent_payload["messages"][1]["content"])
        self.assertIn("最值得关注、最能辅助后续观察决策的3-5个信号", sent_payload["messages"][1]["content"])
        self.assertIn("不要求每条关注点全部满足", sent_payload["messages"][1]["content"])
        self.assertIn("金额、净申购占比、涨跌幅、成交均值占比中任一指标显著异常", sent_payload["messages"][1]["content"])
        self.assertIn("如果多个信号属于同一条资金主线，优先合并表达", sent_payload["messages"][1]["content"])
        self.assertIn("硬约束", sent_payload["messages"][1]["content"])
        self.assertIn("按辅助决策价值从高到低排序，最多输出5个关注点", sent_payload["messages"][1]["content"])
        self.assertIn("不得用最新1日涨跌幅解释20日或60日资金", sent_payload["messages"][1]["content"])
        self.assertIn("二级市场用成交均值占比", sent_payload["messages"][1]["content"])
        self.assertIn("100亿元及以上不保留小数", sent_payload["messages"][1]["content"])
        sent_content = sent_payload["messages"][1]["content"]
        self.assertIn("metric_notes", sent_content)
        self.assertEqual(request.call_args.kwargs["timeout"], DEFAULT_DEEPSEEK_TIMEOUT_SECONDS)
        request.assert_called_once()

    def test_request_deepseek_summary_normalizes_dashboard_terms(self):
        response = {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"headline":"通信净流入且成交热度抬升",'
                            '"focus_items":[{"title":"通信流入强度较高",'
                            '"detail":"近5日净流入64.47亿元，近60日净流出1836.64亿，换手率、成交热度和成交活跃度同步抬升。"}],'
                            '"risks":[],"data_quality":""}'
                        )
                    }
                }
            ]
        }
        with patch("src.capital_flow.ai_summary.request_json", return_value=response):
            summary = request_deepseek_summary(
                build_ai_summary_input(sample_payload()),
                api_key="key",
                model=DEFAULT_DEEPSEEK_MODEL,
                api_url="https://api.deepseek.com/chat/completions",
            )

        self.assertEqual(summary["headline"], "通信净申购且成交均值占比抬升")
        self.assertEqual(summary["focus_items"][0]["title"], "通信净申购占比较高")
        self.assertIn("近5日净申购64.5亿", summary["focus_items"][0]["detail"])
        self.assertIn("近60日净赎回1837亿", summary["focus_items"][0]["detail"])
        self.assertNotIn("1836.64亿", summary["focus_items"][0]["detail"])
        self.assertIn("成交均值占比", summary["focus_items"][0]["detail"])
        self.assertNotIn("成交活跃度", summary["focus_items"][0]["detail"])

    def test_request_deepseek_summary_keeps_at_most_five_focus_items(self):
        items = ",".join(
            f'{{"title":"关注{i}","detail":"第{i}个关注点说明，按重要性排序。"}}'
            for i in range(1, 7)
        )
        response = {
            "choices": [
                {
                    "message": {
                        "content": f'{{"headline":"关注资金流","focus_items":[{items}],"risks":[],"data_quality":""}}'
                    }
                }
            ]
        }
        with patch("src.capital_flow.ai_summary.request_json", return_value=response):
            summary = request_deepseek_summary(
                build_ai_summary_input(sample_payload()),
                api_key="key",
                model=DEFAULT_DEEPSEEK_MODEL,
                api_url="https://api.deepseek.com/chat/completions",
            )

        self.assertEqual(len(summary["focus_items"]), 5)
        self.assertEqual(summary["focus_items"][-1]["title"], "关注5")


if __name__ == "__main__":
    unittest.main()
