# Capital Flow Dashboard

独立的市场资金流向看板。该项目只读调用 TuShare，用于观察市场层面的 ETF 净申购、北上资金和南下资金，不读取、不写入家庭资产项目的数据库，也不参与个人投资收益计算。

## 项目边界

- 本仓库只负责市场资金流向分析。
- 家庭资产、交易录入、持仓收益、产品净值、个人投资看板仍在 `/Users/nova/workspace/data_forge_ws`。
- 两个项目独立运行、独立测试、独立提交；不要在本项目中引入 `portfolio.db` 或个人资产收益逻辑。
- 本项目不写入业务数据库；TuShare 原始响应会缓存在本地 `data/tushare_cache/`，用于减少历史窗口重复拉取。

## 功能

- ETF 净申购金额总览：展示 `1日 / 5日 / 20日 / 60日` 交易日窗口。
- 北上资金、南下资金、宽基被动 ETF、策略因子、A 股行业、港股行业分区展示。
- 总览表首行展示 5 日成交均值占比，用于辅助观察二级市场日均交易热度。
- 明细表展示当日涨跌幅、5 日成交均值占比、各窗口净申购、各窗口净申购占比、当日 ETF 规模。
- 点击明细行可展开 60 日分天涨跌幅、5 日滑动窗口成交均值占比、分天净申购金额和 5 日滑动窗口净申购金额走势。
- 页面头部展示 AI/规则摘要，基于一级市场净申购、二级市场成交热度和涨跌幅提炼关键关注点。
- 宽基 ETF、策略因子、A 股行业、港股行业只展示聚合规模合计不低于 20 亿元的项目。

## 快速接手

```bash
cd /Users/nova/workspace/capital_flow_ws
PYTHON_BIN=/Users/nova/workspace/data_forge_ws/.venv/bin/python scripts/verify_all.sh
```

本机启动：

```bash
scripts/start_web.sh
```

默认服务：

```text
Host: 0.0.0.0
Port: 5083
Local: http://127.0.0.1:5083/
LAN: http://192.168.5.6:5083/
API: http://127.0.0.1:5083/api/capital-flow
```

## 配置

本地配置文件为 `.env.local`，不提交 Git。当前只需要：

```env
TUSHARE_TOKEN=你的TuShareToken
DEEPSEEK_API_KEY=可选DeepSeekKey
DEEPSEEK_MODEL=deepseek-chat
```

`TUSHARE_TOKEN` 通过 `src/config_loader.py` 读取。缺失时 API 会返回 502，并提示 `TUSHARE_TOKEN is not set`。

`DEEPSEEK_API_KEY` 可选。配置后，API 会把压缩后的看板关键数据发送给 DeepSeek 生成页面头部摘要；未配置或调用失败时，自动使用本地规则摘要，不影响核心数据展示。`DEEPSEEK_MODEL` 可按 DeepSeek 当前 API 模型名调整。

## 目录结构

```text
src/app.py                         Flask app 入口
src/capital_flow/routes.py          页面和 API 路由
src/capital_flow/service.py         缓存、窗口选择、API payload 编排
src/capital_flow/ai_summary.py      AI 总结输入压缩、DeepSeek 调用和规则兜底
src/capital_flow/fetcher.py         TuShare 数据拉取
src/capital_flow/calculator.py      北上/南下和 ETF 净申购计算
src/capital_flow/taxonomy_data.json ETF 精确指数分类主数据
src/capital_flow/taxonomy.py        ETF 分类归一化、优先级和关键词兜底
src/capital_flow/taxonomy_audit.py  ETF 分类覆盖率和置信度审计
src/capital_flow/taxonomy_exposure.py ETF 成分股行业暴露审计
src/capital_flow/schema.py          API 返回结构校验
src/static/capital_flow.js          前端交互、表格、展开曲线
src/static/capital_flow.css         页面样式
src/templates/capital_flow.html     页面模板
tests/                              单元测试和前端契约测试
docs/                               架构、运维、数据源、变更记录
```

## 数据缓存

- 进程内 API payload 缓存 30 分钟。
- TuShare 原始数据缓存在 `data/tushare_cache/`，该目录不提交 Git。
- 近期交易日数据缓存 30 分钟，历史交易日数据长期复用；后续日常更新主要补新增交易日。
- 排障时可设置 `CAPITAL_FLOW_DISABLE_FILE_CACHE=1` 临时绕过文件缓存。

## 计算口径摘要

- 北上/南下资金：使用 TuShare `moneyflow_hsgt` 当日净额字段，万元折算为亿元后按窗口累加。
- ETF 净申购金额：ETF 数据日要求目标权益 ETF 价格和份额 100% 同日完整；最新交易日不完整时自动回退到最近完整交易日。
- ETF 每日净申购：使用 `fund_share.fd_share` 相邻交易日份额差，优先乘以同日 `fund_nav.unit_nav`；同日净值缺失时回退同日 `fund_daily.close`，近期净值发布后随短 TTL 缓存自动回填。
- ETF 份额分拆/折算：识别份额倍数突变或缩减且后续价格反向调整的日度点，按可比份额和可比价格计算净申购，避免把基金份额分拆/合并误计为资金流入或流出。
- ETF 净申购占比：使用窗口净申购金额除以窗口期初 ETF 规模，衡量资金流入强度。
- ETF 规模：用于展示、净申购占比分母和成交均值占比分母时，优先使用份额乘以单位净值，净值缺失时再用收盘价估算；后台规模归因审计仍用收盘价市值口径保持代数闭合。
- 5 日成交均值占比：逐日计算场内成交额除以当日期初 ETF 规模后取 5 日均值，衡量二级市场日均交易热度，不等同于一级市场净申购资金流。
- 规模归因审计：API 后台质量字段会校验 `规模变化 ≈ 净申购 + 市场涨跌影响`，用于发现异常份额、价格或净值口径差异。
- 当日 ETF 规模：优先使用最新份额乘以同日单位净值，净值缺失时使用最新收盘价估算。
- 当日/分天涨跌幅：优先使用 `fund_adj` 复权因子计算复权收盘价涨跌幅，覆盖分红、分拆和折算影响，再按当日 ETF 规模加权聚合。
- 宽基被动 ETF：要求跟踪基准明确匹配宽基指数，且宽基匹配时要求 `invest_type = 被动指数型`。
- 行业和策略因子：优先按 `fund_basic.benchmark` 跟踪指数归类，不靠基金简称做主观分类；分类会标记精确映射或关键词兜底，后台可用审计脚本检查覆盖率和低置信度样本。
- A 股行业体系：前台优先沿用中证/国证/上证/深证等跟踪指数名称，后台可用申万 2021 一级行业成分暴露审计主题 ETF，先发现偏差再谨慎调整主数据。
- AI 总结：只读取 API 中的结构化摘要输入，提炼关注点、背离和数据质量提示；不改变任何计算口径，也不作为投资建议。

详细口径见 [docs/data_sources.md](docs/data_sources.md)。

## 验证

```bash
scripts/verify_all.sh
```

验证包含：

- Python 单元测试
- Python 编译检查
- 前端 JavaScript 语法检查
- Git whitespace 检查

常用页面/API 验证：

```bash
curl --noproxy '*' -sS -o /tmp/capital_flow.html -w '%{http_code}\n' http://127.0.0.1:5083/
curl --noproxy '*' -sS -o /tmp/capital_flow.json -w '%{http_code}\n' http://127.0.0.1:5083/api/capital-flow
```

## 文档

- [docs/README.md](docs/README.md)：文档索引和新 session 阅读顺序。
- [docs/architecture.md](docs/architecture.md)：模块边界和请求链路。
- [docs/data_sources.md](docs/data_sources.md)：TuShare 接口、字段和计算口径。
- [docs/operations.md](docs/operations.md)：启动、后台服务、排障和验证。
- [docs/changelog.md](docs/changelog.md)：变更记录。
