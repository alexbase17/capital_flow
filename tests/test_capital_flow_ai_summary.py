import unittest
from unittest.mock import patch

from src.capital_flow.ai_summary import (
    build_ai_summary_input,
    capital_flow_ai_summary,
    parse_model_json,
    request_deepseek_summary,
    rule_based_summary,
)


def sample_payload():
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
        "1d": {**row_base, "net_flow_yi": 8, "net_flow_ratio": 2, "change_pct": 1.2},
        "5d": {**row_base, "net_flow_yi": 30, "net_flow_ratio": 8, "turnover_ratio": 6.2},
        "20d": {**row_base, "net_flow_yi": 80, "net_flow_ratio": 18},
        "60d": {**row_base, "net_flow_yi": 120, "net_flow_ratio": 35},
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
    def test_build_ai_summary_input_includes_compact_signals(self):
        summary_input = build_ai_summary_input(sample_payload())

        self.assertEqual(summary_input["as_of_date"], "2026-06-12")
        self.assertEqual(summary_input["quality"]["scale_audit"]["status"], "ok")
        self.assertEqual(summary_input["signals"][0]["name"], "通信")
        self.assertIn("连续流入", summary_input["signals"][0]["tags"])

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
        self.assertIn("NAV估算占比", summary["data_quality"])

    def test_capital_flow_ai_summary_skips_network_without_key(self):
        with patch("src.capital_flow.ai_summary.get_config", return_value=None), patch(
            "src.capital_flow.ai_summary.request_json"
        ) as request:
            summary = capital_flow_ai_summary(sample_payload())

        self.assertEqual(summary["source"], "rules")
        request.assert_not_called()

    def test_capital_flow_ai_summary_falls_back_when_deepseek_fails(self):
        def fake_config(name, default=None):
            if name == "DEEPSEEK_API_KEY":
                return "key"
            return default

        with patch("src.capital_flow.ai_summary.get_config", side_effect=fake_config), patch(
            "src.capital_flow.ai_summary.request_json", side_effect=TimeoutError("timeout")
        ):
            summary = capital_flow_ai_summary(sample_payload())

        self.assertEqual(summary["status"], "fallback")
        self.assertEqual(summary["source"], "rules")
        self.assertIn("error", summary)

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
                            '"detail":"资金价格成交共振","tags":["共振"]}],'
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
                model="deepseek-chat",
                api_url="https://api.deepseek.com/chat/completions",
            )

        self.assertEqual(summary["headline"], "关注通信")
        self.assertEqual(summary["focus_items"][0]["tags"], ["共振"])
        request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
