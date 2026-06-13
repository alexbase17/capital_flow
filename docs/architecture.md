# 架构说明

更新时间：2026-06-13

## 定位

`capital_flow_ws` 是独立的市场资金流向看板。它从 TuShare 拉取公开市场数据，计算北上/南下资金和 ETF 净申购金额，用于辅助观察市场资金偏好。

本项目与 `/Users/nova/workspace/data_forge_ws` 的家庭资产系统分离：

- 不读取 `portfolio.db`。
- 不写入任何个人投资业务表。
- 不参与持仓、市值、收益率、XIRR 或日收益重算。
- 不依赖家庭资产系统的 Flask app、模板或静态资源。

## 请求链路

```text
浏览器
  -> GET /
  -> src/capital_flow/routes.py
  -> src/templates/capital_flow.html
  -> src/static/capital_flow.js
  -> GET /api/capital-flow
  -> src/capital_flow/service.py
  -> src/capital_flow/fetcher.py
  -> src/tushare_client.py
  -> TuShare Pro HTTP API
```

`/api/capital-flow` 支持参数：

- `window=1d|5d|20d|60d`：选择页面主窗口；返回体仍包含全部窗口的总览数据。
- `refresh=1`：跳过进程内 payload 缓存并重新编排结果；仍会复用 TuShare 文件缓存。

## 后端模块

| 文件 | 职责 |
|---|---|
| `src/app.py` | Flask app 入口，注册资金流向路由 |
| `src/config_loader.py` | 从环境变量和 `.env.local` 读取配置 |
| `src/http_client.py` | 标准库 HTTP JSON 请求封装 |
| `src/tushare_client.py` | TuShare Pro 最小客户端，统一错误处理 |
| `src/capital_flow/routes.py` | 页面路由和 API 路由 |
| `src/capital_flow/service.py` | 缓存、窗口选择、TuShare 拉取编排、payload 校验 |
| `src/capital_flow/ai_summary.py` | AI 总结结构化输入、DeepSeek 调用和本地规则兜底 |
| `src/capital_flow/fetcher.py` | 按接口封装 TuShare 数据读取 |
| `src/capital_flow/policy.py` | 统一维护窗口、规模阈值、缓存 TTL、份额拆分识别容差等口径参数 |
| `src/capital_flow/types.py` | 计算层共享的 TypedDict/dataclass 数据结构 |
| `src/capital_flow/calculator.py` | 北上/南下资金、ETF 净申购、规模、涨跌幅、成交均值占比计算；ETF 主循环拆分为静态信息、最新日指标、日度指标、聚合累加和 payload 组装 |
| `src/capital_flow/taxonomy_data.json` | ETF 精确指数分类主数据，记录 market、asset_class、taxonomy_type、parent_bucket 等后台字段 |
| `src/capital_flow/taxonomy.py` | ETF 分类归一化、优先级、主数据读取和关键词兜底 |
| `src/capital_flow/taxonomy_audit.py` | ETF 分类覆盖率、分类来源、置信度和未分类样本审计 |
| `src/capital_flow/taxonomy_exposure.py` | ETF 跟踪指数成分股行业暴露审计，当前用于 A 股申万 2021 一级行业校验 |
| `src/capital_flow/schema.py` | API 返回结构校验，防止前后端契约漂移 |

## 前端模块

| 文件 | 职责 |
|---|---|
| `src/templates/capital_flow.html` | 首页模板和基础 DOM 容器 |
| `src/static/capital_flow.js` | API 请求、总览矩阵、表格渲染、排序、展开曲线 |
| `src/static/capital_flow.css` | 页面布局、表格、颜色和响应式样式 |

前端不直接保存用户配置，也不写入后端数据。刷新页面或调用 API 会读取后端进程内缓存、本地 TuShare 原始数据缓存或 TuShare 远端数据。

## 缓存

本项目有两层缓存：

1. API payload 进程内缓存：`src/capital_flow/policy.py` 中 `ETF_CACHE_SECONDS = 30 * 60`。
2. TuShare 原始响应文件缓存：`src/capital_flow/fetcher.py` 写入 `data/tushare_cache/`。

API payload 缓存：

- 按窗口 key 保存。
- 默认 API 请求会使用缓存。
- `refresh=1` 会强制刷新 payload。
- 只在当前 Python 进程内存在，服务重启后清空。

TuShare 文件缓存：

- 按接口和日期保存 `fund_daily`、`fund_share`、`fund_nav` 等原始查询结果。
- 近期交易日和最近日期列表缓存 30 分钟。
- 较早交易日数据长期复用，减少 60 个交易日窗口重复拉取。
- 设置 `CAPITAL_FLOW_DISABLE_FILE_CACHE=1` 可临时绕过文件缓存做排障。

## API 返回结构

顶层主要字段：

- `north_south`：当前窗口北上/南下资金。
- `etf`：当前窗口 ETF 数据，包括 `sections`、`coverage`、`quality`。
- `data_status`：当前窗口数据状态，包含 ETF 价格/份额日期对齐信息和北上/南下最新日期。
- `window_payloads`：`1d / 5d / 20d / 60d` 全部窗口数据，用于总览矩阵。
- `windows`：窗口配置。
- `default_window`：默认窗口，当前为 `1d`。
- `selected_window` / `selected_window_label`：当前窗口。
- `threshold_yi`：行业和策略因子的规模展示阈值，当前为 `20`。
- `notes`：页面口径提示。
- `ai_summary`：页面头部摘要，包含 `headline`、`focus_items`、`risks`、`data_quality`、`source` 和 `model`；`focus_items` 使用标题加一到两句自然语言说明，不展示标签；该字段只用于解释展示，不参与任何资金流计算。

AI 总结流程：

1. 后端先从完整 payload 压缩出摘要输入，包括各窗口分区净申购、分区 Top 流入/流出、资金/价格/成交三因子候选信号和质量字段。
2. 未配置 `DEEPSEEK_API_KEY` 时，直接使用本地规则摘要。
3. 配置 DeepSeek 后，调用兼容 OpenAI chat-completions 的 DeepSeek API；默认模型为 `deepseek-v4-flash`，请求关闭 thinking、启用 JSON 输出，并要求关注点使用短句描述原因，不输出前端标签。
4. DeepSeek 调用失败、返回非 JSON 或字段不完整时，自动回退本地规则摘要，核心看板数据不受影响。

ETF 分组行除表格指标外还包含展开图序列：

- `daily_change_pct`：窗口内每日规模加权涨跌幅，用于“分天涨跌幅”走势图。
- `daily_turnover`：窗口内每日成交额和对应日度期初规模，用于“5日滑动窗口成交均值占比”走势图。
- `daily_net_flow`：窗口内每日净申购金额，用于“分天净申购金额”和“5日滑动窗口净申购金额”走势图。
- `scale_audit`：后台规模归因审计，校验规模变化、净申购贡献和市场涨跌影响的残差；不进入前台主表。
- `split_adjusted_count`：该分组中识别并按可比口径调整的 ETF 份额分拆/折算日度点数量。

ETF 数据状态字段：

- `status`：`ready` 或 `fallback`。
- `as_of_date`：ETF 结论使用的数据日。
- `requested_latest_date`：候选 ETF 交易日中的最新日期。
- `latest_price_date` / `latest_share_date`：TuShare 当前可取到的最新价格日和份额日。
- `price_date` / `share_date`：本次计算实际使用的对齐日期。
- `nav_date`：同日单位净值可用日期，缺失时按同日收盘价估算。
- `nav_backfilled_count`：批量日度 `fund_nav` 缺失后，通过单只 ETF 历史净值查询补齐的日度点数量。
- `quality.price_source_label` / `quality.flow_price_status`：标记净申购估值为净值口径、收盘价估算或混合口径。
- `quality.scale_audit`：全页 ETF 分组的规模归因审计汇总。
- `quality.split_adjusted_count`：全页 ETF 分组触发份额分拆/折算调整的日度点数量，用于后台排查异常净申购尖峰。
- `is_aligned`：ETF 价格日和份额日是否对齐；当前服务只输出对齐后的 ETF 结论。
- `required_etf_count`：本次严格完整性检查覆盖的目标权益 ETF 数量。
- `missing_price_count` / `missing_share_count`：最新候选交易日中缺少价格或份额的目标权益 ETF 数量。

页面状态行显示在分区 tab 下方、总览模块上方，用于说明当前全页 ETF 结论的数据日。该行不放入总览卡片，避免用户误以为只约束总览表格。

涨跌幅计算会读取 `fund_adj` 复权因子，用于处理现金分红、份额分拆、合并和折算对收益序列的影响；ETF 净申购金额仍使用真实份额变化和同日单位净值/收盘价，不使用复权价。

ETF 规模、净申购占比分母和成交均值占比分母使用净值优先 AUM 口径；`fund_nav` 先按交易日批量读取，批量缺失但目标 ETF 当日有价格时，再按单只 ETF 拉取窗口历史净值回填，仍缺失才回退收盘价估算。`scale_audit` 独立使用收盘价市值口径做闭合校验，避免把净值和收盘价差异混入规模归因公式。

`etf.sections` 下的 section：

- `broad`：宽基被动 ETF。
- `strategy`：策略因子 ETF。
- `a_industry`：A 股行业 ETF。
- `hk_industry`：港股行业 ETF。

## 测试

| 测试文件 | 覆盖内容 |
|---|---|
| `tests/test_capital_flow_service.py` | TuShare 数据样本、计算口径、分类规则、分类审计、payload 结构 |
| `tests/test_capital_flow_ui_contract.py` | 前端脚本关键契约、字段名、默认排序 |

统一验证入口：

```bash
scripts/verify_all.sh
```

## 变更建议

- 修改计算口径时，先加或改 `tests/test_capital_flow_service.py`。
- 修改 API 字段时，必须同步 `schema.py` 和前端渲染逻辑。
- 修改分类规则时，优先在 `taxonomy_data.json` 增加明确的跟踪指数映射；不要仅凭基金简称做高风险主观归类。修改后运行 `scripts/audit_etf_taxonomy.py`，确认精确映射、关键词兜底和未分类样本变化符合预期。
- 修改 A 股行业/主题边界时，先运行 `scripts/audit_etf_taxonomy.py --with-sw-exposure` 做申万 2021 成分暴露复核；只有暴露结果稳定、指数代码唯一且样本合理时，才更新前台分类主数据。
- 修改页面布局时，至少运行 `node --check src/static/capital_flow.js` 和完整 `scripts/verify_all.sh`。
