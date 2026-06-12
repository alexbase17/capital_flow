# 数据源与计算口径

更新时间：2026-06-13

## 数据源

本项目只读调用 TuShare Pro HTTP API。当前不落库，所有结果由 API 请求时实时拉取并在进程内短缓存。

| TuShare 接口 | 代码位置 | 用途 |
|---|---|---|
| `moneyflow_hsgt` | `src/capital_flow/fetcher.py` | 北上/南下资金当日净额 |
| `fund_basic` | `src/capital_flow/fetcher.py` | ETF 基础信息、基金名称、跟踪基准、投资类型 |
| `fund_daily` | `src/capital_flow/fetcher.py` | ETF 交易日、收盘价 |
| `fund_share` | `src/capital_flow/fetcher.py` | ETF 份额，计算相邻交易日份额变动 |
| `fund_nav` | `src/capital_flow/fetcher.py` | ETF 单位净值，优先用于净申购金额计算 |

TuShare HTTP client 在 `src/tushare_client.py`，配置读取在 `src/config_loader.py`。

## 时间窗口

页面固定展示四个窗口：

| key | 文案 | 含义 |
|---|---|---|
| `1d` | `1日` | 最近 1 个交易日 |
| `3d` | `3日` | 最近 3 个交易日 |
| `7d` | `7日` | 最近 7 个交易日 |
| `30d` | `30日` | 最近 30 个交易日 |

窗口按最近 ETF 交易日计算，不按自然日计算。`1日` 需要最近 2 个交易日的份额数据，因为净申购金额来自相邻交易日份额差。

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
2. 如果同日净值缺失，回退 `fund_daily.close`，记为“收盘价估算”。

单位说明：

- `fd_share` 按 TuShare ETF 份额字段处理。
- 页面展示亿元。
- 除以 `10000` 是把份额乘价格后的金额折算为亿元展示。

质量标记：

- `nav_count`：使用净值口径的日度点数量。
- `close_estimate_count`：使用收盘价估算的日度点数量。
- `skipped_flow_count`：缺少价格或份额导致跳过的日度点数量。
- `price_source_label`：综合展示净值口径、收盘价估算或混合口径。

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
src/capital_flow/taxonomy.py
```

分类原则：

1. 优先使用 `fund_basic.benchmark` 跟踪指数。
2. 明确宽基指数优先归入宽基。
3. 非权益 ETF 排除，例如货币、现金、债券、黄金、商品、境外指数、REIT 等。
4. 策略因子只保留红利、红利低波、价值、质量、成长、现金流等明确 Smart Beta 或风格因子。
5. 指数增强属于主动增强，不纳入策略因子。
6. A 股行业和港股行业只按跟踪指数归类；未匹配标准指数或指数名称规则的 ETF 不纳入行业聚合。

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

- 修改 `taxonomy.py` 后，补充或更新分类测试。
- 修改计算公式后，补充或更新 `tests/test_capital_flow_service.py`。
- 修改 API 字段后，更新 `schema.py`、前端渲染和 `tests/test_capital_flow_ui_contract.py`。
- 修改展示阈值或窗口后，同步更新页面提示、README 和本文档。
- 提交前运行 `scripts/verify_all.sh`。
