import unittest
from pathlib import Path
from unittest.mock import patch

from src.app import app


ROOT_DIR = Path(__file__).resolve().parents[1]


class CapitalFlowUiContractTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def get_text(self, path: str) -> tuple[int, str]:
        response = self.client.get(path)
        try:
            return response.status_code, response.get_data(as_text=True)
        finally:
            response.close()

    def static_text(self, filename: str) -> str:
        return (ROOT_DIR / "src" / "static" / filename).read_text(encoding="utf-8")

    def test_capital_flow_page_is_standalone_homepage(self):
        status, html = self.get_text("/")

        self.assertEqual(status, 200)
        self.assertIn("<h1>资金流向</h1>", html)
        self.assertNotIn('<div class="nav">', html)
        self.assertNotIn('<a href="/" class="active">资金流向</a>', html)
        self.assertRegex(html, r'/static/capital_flow\.css\?v=\d{8}-\d+')
        self.assertRegex(html, r'/static/capital_flow_state\.js\?v=\d{8}-\d+')
        self.assertRegex(html, r'/static/capital_flow_format\.js\?v=\d{8}-\d+')
        self.assertRegex(html, r'/static/capital_flow_data\.js\?v=\d{8}-\d+')
        self.assertRegex(html, r'/static/capital_flow_charts\.js\?v=\d{8}-\d+')
        self.assertRegex(html, r'/static/capital_flow_table\.js\?v=\d{8}-\d+')
        self.assertRegex(html, r'/static/capital_flow\.js\?v=\d{8}-\d+')
        self.assertNotIn("<style>", html)
        self.assertNotIn("onclick=", html)
        self.assertIn("ETF净申购金额", html)
        self.assertIn('class="data-status" id="dataStatus">资金流向数据加载中...</div>', html)
        self.assertIn('<div class="flow-cards" id="totalFlowCards"><div class="empty">资金流向数据加载中...</div></div>', html)
        self.assertIn('<table id="broadTable"><tbody><tr><td class="empty">数据加载中...</td></tr></tbody></table>', html)
        self.assertIn('id="aiSummaryPanel"', html)
        self.assertIn('id="aiSummaryPanel" aria-label="AI资金流向总结" hidden', html)
        self.assertIn("AI总结", html)
        self.assertLess(
            html.index('class="section-nav"'),
            html.index('class="data-status" id="dataStatus"'),
        )
        self.assertLess(
            html.index('class="data-status" id="dataStatus"'),
            html.index('id="aiSummaryPanel"'),
        )
        self.assertLess(
            html.index('id="aiSummaryPanel"'),
            html.index('id="capital-section-total" data-section="total"'),
        )
        self.assertIn("宽基被动ETF", html)
        self.assertNotIn("宽基被动ETF(>=20亿) <span", html)
        self.assertIn("A股行业", html)
        self.assertIn("港股行业", html)
        self.assertIn("策略因子", html)
        self.assertNotIn("策略/因子", html)
        self.assertNotIn('aria-label="资金流向时间窗口"', html)
        self.assertNotIn('id="windowButtons"', html)
        self.assertNotIn('id="flowDateRange"', html)
        self.assertNotIn("资金流向总览", html)
        self.assertIn('aria-label="资金流向分组导航"', html)
        self.assertIn('href="#capital-section-total" class="active" data-section-link="total">总览</a>', html)
        self.assertIn('href="#capital-section-broad" data-section-link="broad">宽基</a>', html)
        self.assertIn('href="#capital-section-a-industry" data-section-link="a_industry">A股行业</a>', html)
        self.assertIn('href="#capital-section-hk-industry" data-section-link="hk_industry">港股行业</a>', html)
        self.assertIn('href="#capital-section-strategy" data-section-link="strategy">策略因子</a>', html)
        self.assertLess(
            html.index('href="#capital-section-hk-industry" data-section-link="hk_industry">港股行业</a>'),
            html.index('href="#capital-section-strategy" data-section-link="strategy">策略因子</a>'),
        )
        self.assertIn('id="capital-section-total" data-section="total"', html)
        self.assertIn('id="capital-section-broad" data-section="broad"', html)
        self.assertIn('id="capital-section-a-industry" data-section="a_industry"', html)
        self.assertIn('id="capital-section-hk-industry" data-section="hk_industry"', html)
        self.assertIn('id="capital-section-strategy" data-section="strategy"', html)
        self.assertLess(
            html.index('id="capital-section-hk-industry" data-section="hk_industry"'),
            html.index('id="capital-section-strategy" data-section="strategy"'),
        )
        self.assertNotIn("权益 ETF 分类覆盖率", html)
        self.assertNotIn("北上/南下资金流向", html)
        self.assertIn("优先按基金跟踪基准归类", html)
        self.assertIn("优先于名称中的行业词", html)
        self.assertIn("仅展示同一主题 ETF 最新规模合计超过 20 亿元", html)
        self.assertIn("20 亿元的行业/主题", html)
        self.assertIn("指数增强属于主动增强，不纳入本表", html)
        self.assertNotIn('id="refreshFlowBtn"', html)

    def test_capital_flow_api_returns_service_payload(self):
        payload = {
            "north_south": {"latest_date": "2026-06-11", "previous_date": "2026-06-10", "rows": []},
            "etf": {"latest_date": "2026-06-11", "previous_date": "2026-06-10", "sections": {}},
            "threshold_yi": 20,
            "notes": [],
        }
        with patch("src.capital_flow.routes.capital_flow_payload", return_value=payload) as service:
            response = self.client.get("/api/capital-flow")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), payload)
        service.assert_called_once_with(force_refresh=False, window_key=None)

    def test_capital_flow_ai_summary_api_uses_cached_payload(self):
        payload = {"etf": {"latest_date": "2026-06-11"}, "window_payloads": {}}
        summary = {
            "status": "ready",
            "source": "deepseek",
            "headline": "资金流向分化",
            "focus_items": [],
            "risks": [],
            "data_quality": "数据正常",
        }
        with patch("src.capital_flow.routes.capital_flow_payload", return_value=payload) as service, patch(
            "src.capital_flow.routes.capital_flow_ai_summary", return_value=summary
        ) as ai_summary:
            response = self.client.get("/api/capital-flow/ai-summary?window=5d")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ai_summary": summary})
        service.assert_called_once_with(force_refresh=False, window_key="5d")
        ai_summary.assert_called_once_with(payload, use_deepseek=True, use_cache=True)

    def test_capital_flow_ai_summary_api_bypasses_ai_cache_on_refresh(self):
        payload = {"etf": {"latest_date": "2026-06-11"}, "window_payloads": {}}
        summary = {
            "status": "ready",
            "source": "deepseek",
            "headline": "资金流向分化",
            "focus_items": [],
            "risks": [],
            "data_quality": "",
        }
        with patch("src.capital_flow.routes.capital_flow_payload", return_value=payload) as service, patch(
            "src.capital_flow.routes.capital_flow_ai_summary", return_value=summary
        ) as ai_summary:
            response = self.client.get("/api/capital-flow/ai-summary?refresh=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ai_summary": summary})
        service.assert_called_once_with(force_refresh=True, window_key=None)
        ai_summary.assert_called_once_with(payload, use_deepseek=True, use_cache=False)

    def test_capital_flow_static_scripts_render_expected_sections(self):
        html = (ROOT_DIR / "src" / "templates" / "capital_flow.html").read_text(encoding="utf-8")
        script = "\n".join(
            self.static_text(filename)
            for filename in (
                "capital_flow_state.js",
                "capital_flow_format.js",
                "capital_flow_data.js",
                "capital_flow_charts.js",
                "capital_flow_table.js",
                "capital_flow.js",
            )
        )
        css = self.static_text("capital_flow.css")

        self.assertIn('"/api/capital-flow"', script)
        self.assertIn("/api/capital-flow/ai-summary?", script)
        self.assertNotIn("refresh=1", script)
        self.assertIn("function renderTotalFlow", script)
        self.assertIn("function renderDataStatus", script)
        self.assertIn("function renderAiSummary", script)
        self.assertIn("function loadDeepSeekSummary", script)
        self.assertIn("loadDeepSeekSummary(data)", script)
        self.assertIn("DeepSeek摘要加载失败，隐藏AI总结", script)
        self.assertIn('summary.source === "deepseek"', script)
        self.assertIn("panel.hidden = !shouldShow", script)
        self.assertIn('source.textContent = summary.model || "";', script)
        self.assertNotIn('const sourceLabel = "DeepSeek"', script)
        self.assertIn("ai_summary", script)
        self.assertNotIn("ai-summary-tags", script)
        self.assertIn("function yiFractionDigits", script)
        self.assertIn("if (absValue >= 100) return 0;", script)
        self.assertIn("if (absValue >= 10) return 1;", script)
        self.assertIn("yiFmtByDigits[digits].format", script)
        self.assertNotIn("function renderWindowButtons", script)
        self.assertNotIn("function activeWindowData", script)
        self.assertNotIn("function renderFlowDateRange", script)
        self.assertIn("function renderCapitalFlow", script)
        self.assertIn("function setupSectionNav", script)
        self.assertIn("function initializeCapitalFlowPage", script)
        self.assertIn("DOMContentLoaded", script)
        self.assertEqual(script.count("loadCapitalFlow();"), 1)
        self.assertEqual(script.count("setupSectionNav();"), 1)
        self.assertIn("function sortableHeader", script)
        self.assertIn("function sortedRows", script)
        self.assertIn("function bindTableSort", script)
        self.assertIn('const defaultTableSort = { key: "flow_1d", order: "desc" };', script)
        self.assertIn("function pxVar", script)
        self.assertIn("function activeSectionFromScroll", script)
        self.assertIn('pxVar("--capital-section-nav-height", 62)', script)
        self.assertIn("requestAnimationFrame", script)
        self.assertIn('window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });', script)
        self.assertIn("[data-section-link]", script)
        self.assertIn("ETF净申购金额", script)
        self.assertIn("ETF数据日", script)
        self.assertIn("价格日", script)
        self.assertIn("份额日", script)
        self.assertIn("净申购估值", script)
        self.assertIn("使用上次成功缓存", script)
        self.assertIn(".ai-summary-list", css)
        self.assertIn(".ai-summary-list { display: grid; gap: 16px; }", css)
        self.assertIn("font-size: 13.6px", css)
        self.assertIn("color: #243244", css)
        self.assertIn(".ai-summary-source { color: #667386; font-size: 12px; font-weight: 400; }", css)
        self.assertNotIn(".ai-summary-risks", css)
        self.assertNotIn(".ai-summary-item::before", css)
        self.assertNotIn("max-width: 920px", css)
        self.assertNotIn(".ai-summary-item:first-child", css)
        self.assertNotIn(".ai-summary-item { min-width: 0; padding: 10px 0; border-top", css)
        self.assertNotIn(".ai-summary-grid", css)
        self.assertNotIn(".ai-summary-foot", css)
        self.assertNotIn(".ai-summary-tags", css)
        self.assertIn('status.status === "fallback" ? " warning" : ""', script)
        self.assertNotIn('status.payload_cache_status === "stale" ? " warning"', script)
        self.assertIn("已回退到最近完整交易日", script)
        self.assertIn("北上资金", script)
        self.assertIn("南下资金", script)
        self.assertIn("宽基被动ETF(>=20亿)", script)
        self.assertIn("策略因子(>=20亿)", script)
        self.assertIn("A股行业(>=20亿)", script)
        self.assertIn("港股行业(>=20亿)", script)
        self.assertIn('const sectionIds = ["total", "broad", "a_industry", "hk_industry", "strategy"];', script)
        self.assertNotIn("策略/因子", script)
        self.assertIn('const windowKeys = ["1d", "5d", "20d", "60d"];', script)
        self.assertNotIn('"3d"', script)
        self.assertIn("function windowPayload", script)
        self.assertIn("function mergeRowsForSection", script)
        self.assertIn("function renderFlowChart", script)
        self.assertIn("function toggleRow", script)
        self.assertIn("function expandedRowScrollOffset", script)
        self.assertIn("function scrollExpandedRowIntoView", script)
        self.assertIn("+ tableHeadHeight - 1", script)
        self.assertIn("function formatIndexName", script)
        self.assertIn("row.display_name || row.index_name", script)
        self.assertIn("row.index_code", script)
        self.assertIn("function bindNameTooltips", script)
        self.assertIn('data-name-tooltip="${escapeHtml(displayName)}"', script)
        self.assertIn('cell.classList.toggle("has-name-tooltip", isOverflowing)', script)
        self.assertIn('class="name-text"', script)
        self.assertNotIn("currentWindowKey", script)
        self.assertNotIn("data-window-key", script)
        self.assertNotIn("全量宽基ETF", script)
        self.assertNotIn("权益ETF分类覆盖率", script)
        self.assertNotIn("target_coverage_pct", script)
        self.assertNotIn('"总计"', script)
        self.assertNotIn("renderNorthSouth", script)
        self.assertNotIn("total_net_flow_yi", script)
        self.assertNotIn('"hsgt"', script.split("const sectionIds", 1)[1].split("];", 1)[0])
        self.assertNotIn("优先净值，缺失估算", script)
        self.assertIn('renderTable("broadTable"', script)
        self.assertIn('renderTable("aIndustryTable"', script)
        self.assertIn('renderTable("hkIndustryTable"', script)
        self.assertIn('renderTable("strategyTable"', script)
        self.assertIn('sortableHeader(tableId, "change_pct", "当日涨跌幅"', script)
        self.assertIn('sortableHeader(tableId, "turnover_5d", "5日成交均值占比"', script)
        self.assertIn("flow_1d", script)
        self.assertIn("`flow_${key}`", script)
        self.assertIn("`ratio_${key}`", script)
        self.assertIn("turnover_ratio", script)
        self.assertIn("daily_turnover", script)
        self.assertIn("windowTradeLabels", script)
        self.assertIn('"1d": "近1个交易日"', script)
        self.assertIn('"60d": "近60个交易日"', script)
        self.assertNotIn("3交易日", script)
        self.assertNotIn("flow_7d", script)
        self.assertNotIn("flow_30d", script)
        self.assertIn("row[`ratio_${key}`]", script)
        self.assertIn("daily_change_pct", script)
        self.assertNotIn("ratio_7d", script)
        self.assertNotIn("ratio_30d", script)
        self.assertIn("windowKeys.length * 2 + 4", script)
        self.assertIn("5日滑动窗口成交均值占比", script)
        self.assertIn("分天涨跌幅", script)
        self.assertIn("分天净申购金额", script)
        self.assertIn("5日滑动窗口净申购金额", script)
        self.assertIn("function rollingWindowPoints", script)
        self.assertIn("function rollingTurnoverRatioPoints", script)
        self.assertIn("function renderDailyChangeLine", script)
        self.assertIn("function renderDailyFlowBars", script)
        self.assertIn("function renderRollingFlowLine", script)
        self.assertIn("function renderRollingTurnoverRatioLine", script)
        self.assertNotIn("function shortDateLabel", script)
        self.assertNotIn("function renderChartRangeTicks", script)
        self.assertNotIn("chart-range", script)
        self.assertIn("flow-chart-viewport", script)
        self.assertIn("flow-chart-body", script)
        self.assertIn("function bindChartTooltips", script)
        self.assertIn("function nearestTooltipIndex", script)
        self.assertIn("data-chart-tooltips", script)
        self.assertIn('preserveAspectRatio="none"', script)
        self.assertIn("pointermove", script)
        self.assertIn("item.label", script)
        self.assertIn("item.x", script)
        self.assertIn("tooltip.offsetWidth", script)
        self.assertIn("Math.min(tooltip.offsetWidth, rect.width - margin * 2)", script)
        self.assertIn("start_date", script)
        self.assertIn("end_date", script)
        self.assertIn('windowHeader(tableId, key, "flow", "净申购"', script)
        self.assertIn('windowHeader(tableId, key, "ratio", "净申购占比"', script)
        self.assertIn("资金流入强度", html)
        self.assertIn("hideZeroLine", script)
        self.assertIn("alignTitleCenter", script)
        self.assertIn("5日成交均值占比 = 近5个交易日逐日计算 场内成交额 / 当日期初 ETF 规模 后取均值", html)
        self.assertIn("状态栏会标记净申购估值口径", html)
        self.assertIn("表格口径：当日涨跌幅为最新交易日复权涨跌幅并按 ETF 规模加权", html)
        self.assertNotIn("${windowLabels[key]}净申购金额", script)
        self.assertNotIn("${windowLabels[key]}净申购金额占比", script)
        self.assertIn("当日ETF规模", script)
        self.assertIn("data-sort-key", script)
        self.assertIn("data-next-order", script)
        self.assertNotIn("sort-arrow", script)
        self.assertIn("复权涨跌幅", html)
        self.assertNotIn("<th>口径</th>", script)
        self.assertNotIn("<th>主要ETF</th>", script)
        self.assertNotIn("renderEtfList", script)
        self.assertIn("quality.price_source_label", script)
        self.assertIn("同日单位净值", html)
        self.assertIn("份额日期相邻差", html)
        self.assertNotIn("正数表示净申购，负数表示净赎回", script)
        self.assertNotIn("规模过滤阈值", script)
        self.assertNotIn("renderNotes", script)
        self.assertIn(".positive", css)
        self.assertIn(".negative", css)
        self.assertIn(".positive { color: #047857; }", css)
        self.assertIn(".negative { color: #b91c1c; }", css)
        self.assertIn("th.num-head { text-align: right;", css)
        self.assertIn("thead th { position: sticky;", css)
        self.assertIn("top: calc(var(--capital-header-height) + var(--capital-section-nav-height))", css)
        self.assertIn("border-right: 0", css)
        self.assertIn("border-left: 0", css)
        self.assertIn("box-shadow: inset 0 -1px 0 #d9e0ea", css)
        self.assertIn(".sort-button", css)
        self.assertNotIn(".section-window-toolbar", css)
        self.assertIn(".section-links", css)
        self.assertIn(".data-status", css)
        self.assertIn(".data-status.warning", css)
        self.assertNotIn(".window-button.active", css)
        self.assertIn(".flow-matrix", css)
        self.assertIn(".data-row", css)
        self.assertIn(".detail-row", css)
        self.assertIn("--capital-name-column-width", css)
        self.assertIn(".flow-chart-viewport", css)
        self.assertIn(".flow-chart", css)
        self.assertIn(".flow-chart-stack", css)
        self.assertIn("position: sticky", css)
        self.assertIn(".table-wrap { overflow-x: visible; }", css)
        self.assertIn("@media (max-width: 1274px)", css)
        self.assertIn("grid-template-columns: var(--capital-name-column-width) minmax(0, 1fr)", css)
        self.assertIn("min-width: 1234px", css)
        self.assertIn("--capital-name-column-width: 156px", css)
        self.assertIn("td:nth-child(n+2) { width: 98px; }", css)
        self.assertIn("text-overflow: ellipsis", css)
        self.assertIn(".name-cell.has-name-tooltip:hover::after", css)
        self.assertIn("content: attr(data-name-tooltip)", css)
        self.assertIn(".flow-line", css)
        self.assertIn(".flow-bar", css)
        self.assertIn(".positive-bar", css)
        self.assertIn(".negative-bar", css)
        self.assertIn(".rolling-point", css)
        self.assertIn(".chart-hover-layer", css)
        self.assertIn("--zero-y", css)
        self.assertNotIn(".chart-range", css)
        self.assertNotIn(".chart-tick", css)
        self.assertIn(".chart-tooltip", css)
        self.assertIn(".chart-tooltip.visible", css)
        self.assertIn(".chart-title.center", css)
        self.assertIn("height: 132px", css)
        self.assertIn("width: max-content", css)
        self.assertIn("overflow-wrap: normal", css)
        self.assertIn("white-space: nowrap", css)
        self.assertIn("cursor: default", css)
        self.assertIn("margin-left: 0", css)
        self.assertIn("text-align: left", css)
        self.assertIn(".sort-button::before", css)
        self.assertIn('.sort-button[data-sort-order="asc"]::before', css)
        self.assertIn('.sort-button[data-sort-order="desc"]::before', css)
        self.assertNotIn(".sort-button:hover::before", css)
        self.assertNotIn(".sort-button:hover, .sort-button.active", css)
        self.assertNotIn(".sort-arrow", css)
        self.assertIn(".section-nav", css)
        self.assertIn("--capital-header-height", css)
        self.assertIn("--capital-section-nav-height", css)
        self.assertIn("--capital-section-gap", css)
        self.assertIn("--capital-section-nav-height: 62px", css)
        self.assertIn("padding: calc(10px + var(--capital-section-gap)) 0 14px", css)
        self.assertIn(".summary-panel .panel-header { border-bottom: 0;", css)
        self.assertIn("padding-top: calc(var(--capital-header-height) + var(--capital-section-nav-height))", css)
        self.assertIn(".header { position: fixed;", css)
        self.assertIn(".section-nav { position: fixed;", css)
        self.assertIn("top: var(--capital-header-height)", css)
        self.assertIn(".help-tip", css)
        self.assertIn("overflow: visible", css)
        self.assertIn("vertical-align: middle", css)
        self.assertNotIn(".source-cell", css)
        self.assertIn("table-layout: fixed", css)


if __name__ == "__main__":
    unittest.main()
