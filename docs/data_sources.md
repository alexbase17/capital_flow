# 数据源与计算口径

更新时间：2026-06-13

## 数据源

本项目只读调用 TuShare Pro HTTP API，不写入业务数据库。TuShare 原始响应会缓存在本地 `data/tushare_cache/`，用于减少历史窗口重复拉取。

| TuShare 接口 | 代码位置 | 用途 |
|---|---|---|
| `moneyflow_hsgt` | `src/capital_flow/fetcher.py` | 北上/南下资金当日净额 |
| `fund_basic` | `src/capital_flow/fetcher.py` | ETF 基础信息、基金名称、跟踪基准、投资类型 |
| `fund_daily` | `src/capital_flow/fetcher.py` | ETF 交易日、收盘价 |
| `fund_share` | `src/capital_flow/fetcher.py` | ETF 份额，计算相邻交易日份额变动 |
| `fund_nav` | `src/capital_flow/fetcher.py` | ETF 单位净值，优先用于净申购金额计算 |

TuShare HTTP client 在 `src/tushare_client.py`，配置读取在 `src/config_loader.py`。

## TuShare 原始数据缓存

缓存位置：

```text
data/tushare_cache/
```

该目录已加入 `.gitignore`，不提交 Git。

缓存规则：

- `fund_daily`、`fund_share`、`fund_nav` 按接口和交易日缓存。
- 近期交易日数据缓存 30 分钟，避免盘后更新未完成时永久保存半成品。
- 较早交易日数据长期复用，服务重启后也不需要重复拉取完整 60 日历史窗口。
- `fund_basic` 等参考数据缓存 24 小时。
- 北上/南下最近窗口和 ETF 最近交易日列表缓存 30 分钟。

排障或强制核对远端数据时，可临时设置：

```bash
CAPITAL_FLOW_DISABLE_FILE_CACHE=1 scripts/start_web.sh
```

## 时间窗口

页面固定展示五个窗口：

| key | 文案 | 含义 |
|---|---|---|
| `1d` | `1日` | 最近 1 个交易日 |
| `3d` | `3日` | 最近 3 个交易日 |
| `5d` | `5日` | 最近 5 个交易日，近一周 |
| `20d` | `20日` | 最近 20 个交易日，近一月 |
| `60d` | `60日` | 最近 60 个交易日，近一季 |

窗口按最近 ETF 交易日计算，不按自然日计算。页面中的“日”均指 ETF 有效交易日。`1日` 需要最近 2 个交易日的份额数据，因为净申购金额来自相邻交易日份额差。

## ETF 数据日期对齐

ETF 净申购计算要求价格日和份额日硬对齐：

- 服务会先读取一段候选 ETF 交易日。
- ETF 数据日采用最严格口径：最新候选交易日份额接口中出现的目标权益 ETF，必须 100% 同日存在 `fund_daily.close` 和 `fund_share.fd_share`，该交易日才可作为全页 ETF 结论的数据日。
- 严格检查样本池以 `fund_share` 为基准，因为 ETF 净申购必须依赖份额变化；只有价格、没有份额的 ETF 无法参与净申购计算，不应阻断全页数据。
- 严格检查样本池不直接使用 `fund_basic` 全量上市基金，因为其中可能包含尚未在当日份额接口出现、停牌、刚上市或数据暂未同步的 ETF；否则会导致没有任何交易日可用。
- 如果最新 ETF 交易日任一活跃目标权益 ETF 缺少价格或份额，则自动回退到最近一个活跃目标权益 ETF 价格、份额 100% 完整的交易日。
- 回退后的历史窗口仍按价格接口和份额接口均有数据的交易日向前取数；具体 ETF 在历史窗口内因上市时间或数据缺口无法计算的日度点会在计算层跳过，避免新上市 ETF 破坏整个 60 日窗口。
- 如果回退后仍无法满足 `60日` 窗口所需的完整交易日数量，API 返回错误，不输出可能错配的 ETF 结论。

`fund_nav.unit_nav` 不参与硬对齐。净值只作为同日优先价格源；同日净值缺失时，使用同日 `fund_daily.close` 估算，并在质量字段中标记为“收盘价估算”或“混合口径”。

API 和页面会展示 ETF 数据状态：

- `as_of_date`：当前 ETF 结论使用的数据日。
- `price_date`：当前 ETF 结论使用的价格日。
- `share_date`：当前 ETF 结论使用的份额日。
- `nav_date`：同日净值可用日期；缺失时页面显示收盘价估算。
- `status`：`ready` 表示最新候选日可用，`fallback` 表示已回退到最近完整交易日。
- `is_aligned`：用于标识价格日和份额日是否对齐；ETF 结论只在该值为 `true` 时输出。
- `required_etf_count`：严格完整性检查覆盖的目标权益 ETF 数量。
- `missing_price_count` / `missing_share_count`：最新候选交易日中缺少价格或份额的目标权益 ETF 数量；前台暂不展开展示，后台用于排障。

## 北上/南下资金

接口：

```text
moneyflow_hsgt
```

计算：

```text
窗口净流入金额 = sum(当日净额字段) * 0.0001
```

单位说明：

- TuShare 返回金额按万元口径处理。
- 页面展示亿元。
- `HSGT_UNIT_TO_YI = 0.0001`。

当前展示：

- 北上资金
- 南下资金

北上/南下资金不与 ETF 净申购金额直接相加，页面总览只是并列展示不同资金来源。

## ETF 净申购金额

核心公式：

```text
每日净申购份额 = 当日 fd_share - 上一交易日 fd_share
每日净申购金额 = 每日净申购份额 * 当日价格 / 10000
窗口净申购金额 = sum(窗口内每日净申购金额)
```

价格选择：

1. 优先使用同日 `fund_nav.unit_nav`，记为“净值口径”。
2. 如果同日净值缺失，回退同日 `fund_daily.close`，记为“收盘价估算”。

单位说明：

- `fd_share` 按 TuShare ETF 份额字段处理。
- 页面展示亿元。
- 除以 `10000` 是把份额乘价格后的金额折算为亿元展示。

质量标记：

- `nav_count`：使用净值口径的日度点数量。
- `close_estimate_count`：使用收盘价估算的日度点数量。
- `skipped_flow_count`：缺少价格或份额导致跳过的日度点数量。
- `price_source_label`：综合展示净值口径、收盘价估算或混合口径。

## ETF 净申购占比

计算：

```text
窗口期初 ETF 规模 = 窗口起点 fd_share * 窗口起点 close / 10000
净申购占比 = 窗口净申购金额 / 窗口期初 ETF 规模 * 100
```

窗口起点是该窗口最早的相邻交易日。例如 `20日` 窗口使用第 21 个交易日作为期初规模日。

该口径用于衡量资金流入强度，避免用最新规模作分母时被窗口内大额申购抬高后的规模稀释。页面仍单独展示“当日 ETF 规模”，用于判断当前主题体量和展示阈值。

## 当日 ETF 规模

计算：

```text
当日 ETF 规模 = 最新 fd_share * 最新 close / 10000
```

页面展示亿元。该规模用于：

- 表格展示“当日 ETF 规模”。
- 行业、港股行业、策略因子的 20 亿元展示阈值。
- 当日涨跌幅聚合的规模权重。

## 当日涨跌幅

单只 ETF：

```text
涨跌幅 = (最新 close - 上一窗口交易日 close) / 上一窗口交易日 close * 100
```

聚合项：

```text
聚合涨跌幅 = sum(单只涨跌幅 * 单只规模) / sum(可计算涨跌幅的单只规模)
```

如果缺少上一交易日收盘价，则该 ETF 不参与聚合涨跌幅。

## ETF 分类

分类入口：

```text
src/capital_flow/taxonomy_data.json
src/capital_flow/taxonomy.py
```

`taxonomy_data.json` 是高置信度精确映射主数据；`taxonomy.py` 负责跟踪指数名称归一化、分类优先级、主数据读取和关键词兜底。

分类审计入口：

```bash
.venv/bin/python scripts/audit_etf_taxonomy.py
.venv/bin/python scripts/audit_etf_taxonomy.py --with-sw-exposure --exposure-limit 30
```

分类原则：

1. 优先使用 `fund_basic.benchmark` 跟踪指数。
2. 明确宽基指数优先归入宽基。
3. 非权益 ETF 排除，例如货币、现金、债券、黄金、商品、境外指数、REIT 等。
4. 策略因子只保留红利、红利低波、价值、质量、成长、现金流等明确 Smart Beta 或风格因子。
5. 指数增强属于主动增强，不纳入策略因子。
6. A 股行业和港股行业只按跟踪指数归类；未匹配标准指数或指数名称规则的 ETF 不纳入行业聚合。
7. A 股行业前台展示优先参考中证、国证、上证、深证等 ETF 实际跟踪指数名称；申万 2021 作为后台成分暴露校验体系，不直接覆盖前台名称。
8. 主题 ETF 不硬塞进传统行业；后台先用成分股暴露判断其是否明显集中在单一申万一级行业，再决定是否调整主数据。

分类来源和置信度：

- `benchmark_exact`：明确跟踪指数映射，置信度 `high`，优先补充这种规则。
- `benchmark_pattern`：指数名称关键词兜底，置信度 `medium`，用于避免新指数完全漏分，但需要通过审计逐步补成精确映射。
- 未分类目标权益 ETF 不进入行业/策略聚合，避免用低质量猜测污染前台趋势。

成分暴露审计：

- `--with-sw-exposure` 会额外调用 TuShare `index_classify`、`index_member`、`index_basic`、`index_weight`。
- `index_classify` 和 `index_member` 用于建立股票到申万 2021 一级行业的映射。
- `index_basic` 用于把跟踪指数名称解析到指数代码；解析时会按中证、上证、深证/国证做发布方兼容过滤，避免只靠短名称跨体系误配。
- `index_weight` 用于读取指数最新成分权重，并聚合出前五大申万一级行业暴露。
- 开启暴露审计时，脚本会用最近 ETF 价格和份额估算当前规模，按规模从高到低优先检查高影响跟踪指数。
- `exposures`、`missing_index_code_samples` 和 `no_weight_samples` 会带 `scale_yi`、`etf_count`，用于优先补齐影响最大的指数代码。
- `label_consistency` 会检查同一前台标签下不同跟踪指数的申万 top 行业是否一致；不一致时只作为后台预警，不自动拆分或改名前台标签。
- 审计结果只作为后台复核信号，不自动改变前台分类。前台分类仍以 `taxonomy_data.json` 的明确映射为准。
- `missing_index_code_count` 表示还没有可靠解析到指数代码的样本；`not_checked_due_limit_count` 表示因为 `--exposure-limit` 限额本轮未查询权重的样本。

主数据字段：

- `benchmark`：归一化后的跟踪指数名称。
- `section`：前台模块，取值为 `broad`、`strategy`、`a_industry`、`hk_industry` 或 `excluded`。
- `label`：前台聚合名称。
- `market`：A股、港股、海外等后台市场标签。
- `asset_class`：资产类别，例如 `equity`。
- `taxonomy_type`：`broad`、`industry`、`theme`、`factor` 等后台分类类型。
- `parent_bucket`：后台大类，用于审计行业结构，不直接展示到前台。
- `index_code`：可选指数代码；宽基用于前台指数代码展示，行业/主题当前主要用于后台成分暴露审计。少数中证指数只有全收益代码可稳定取得成分权重，这类代码仅作为后台审计辅助，不改变前台标签口径。

当前高确定性优化已覆盖更多明确指数，包括深证50、国证2000、中证800、中小100、金融科技、数字经济、消费电子、航空航天、卫星通信、港股汽车、港股创新药等；并为证券、通信设备、化工、创新药、银行、工业有色、机器人等高影响 A 股指数补充了已验证可用于成分暴露的指数代码。巴西、印度、越南、韩国、英国、欧洲、全球等非港股海外 ETF 会被排除。

分类结果：

| section | 页面模块 | 说明 |
|---|---|---|
| `broad` | 宽基被动 ETF | 宽基指数，被动指数型 |
| `strategy` | 策略因子 | 明确 Smart Beta 或风格因子 |
| `a_industry` | A 股行业 | A 股行业或主题指数 |
| `hk_industry` | 港股行业 | 港股行业或主题指数 |

## 展示阈值

常量：

```text
MIN_INDEX_SCALE_YI = 20.0
```

规则：

- 宽基被动 ETF 不应用该阈值。
- 策略因子、A 股行业、港股行业按同一聚合主题的最新规模合计过滤。
- 规模合计低于 20 亿元的聚合项不展示，减少噪音。

## 与机构数据差异

本项目与 Wind 或其他机构数据可能不同，主要差异来源：

- ETF 样本池不同：机构可能有自维护 ETF 池。
- 分类标准不同：机构可能按申万、中信、中证、Wind 行业或人工主题分类。
- 日期口径不同：机构可能按公告日、确认日或交易日展示。
- 价格口径不同：机构可能统一用净值，也可能用收盘价估算。
- 场内/场外口径不同：本项目当前聚焦 ETF，不把场外指数基金直接相加。
- 数据更新时间不同：TuShare、Wind、基金公告和券商终端更新时间可能不同。

因此本项目目标是提供可解释、可追踪、可复核的市场方向参考，不承诺逐项等于某一家机构展示。

## 修改口径时的检查清单

- 修改 `taxonomy_data.json` 或 `taxonomy.py` 后，补充或更新分类测试，并运行 `.venv/bin/python scripts/audit_etf_taxonomy.py` 对比覆盖率、关键词兜底样本和未分类样本。
- 修改计算公式后，补充或更新 `tests/test_capital_flow_service.py`。
- 修改 API 字段后，更新 `schema.py`、前端渲染和 `tests/test_capital_flow_ui_contract.py`。
- 修改展示阈值或窗口后，同步更新页面提示、README 和本文档。
- 提交前运行 `scripts/verify_all.sh`。
