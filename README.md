# Capital Flow Dashboard

独立的市场资金流向看板。该项目只读调用 TuShare，用于观察市场层面的 ETF 净申购、北上资金和南下资金，不读取、不写入家庭资产项目的数据库，也不参与个人投资收益计算。

## 项目边界

- 本仓库只负责市场资金流向分析。
- 家庭资产、交易录入、持仓收益、产品净值、个人投资看板仍在 `/Users/nova/workspace/data_forge_ws`。
- 两个项目独立运行、独立测试、独立提交；不要在本项目中引入 `portfolio.db` 或个人资产收益逻辑。
- 本项目当前不落库，页面数据来自 API 实时拉取和进程内短缓存。

## 功能

- ETF 净申购金额总览：展示 `1日 / 3日 / 7日 / 30日` 窗口。
- 北上资金、南下资金、宽基被动 ETF、策略因子、A 股行业、港股行业分区展示。
- 明细表展示当日涨跌幅、各窗口净申购金额、各窗口净申购金额占比、当日 ETF 规模。
- 点击明细行可展开 30 日净申购金额曲线。
- 宽基 ETF 不设规模阈值；策略因子、A 股行业、港股行业只展示主题规模合计不低于 20 亿元的聚合项。

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
```

`TUSHARE_TOKEN` 通过 `src/config_loader.py` 读取。缺失时 API 会返回 502，并提示 `TUSHARE_TOKEN is not set`。

## 目录结构

```text
src/app.py                         Flask app 入口
src/capital_flow/routes.py          页面和 API 路由
src/capital_flow/service.py         缓存、窗口选择、API payload 编排
src/capital_flow/fetcher.py         TuShare 数据拉取
src/capital_flow/calculator.py      北上/南下和 ETF 净申购计算
src/capital_flow/taxonomy.py        ETF 宽基、策略因子、行业分类规则
src/capital_flow/schema.py          API 返回结构校验
src/static/capital_flow.js          前端交互、表格、展开曲线
src/static/capital_flow.css         页面样式
src/templates/capital_flow.html     页面模板
tests/                              单元测试和前端契约测试
docs/                               架构、运维、数据源、变更记录
```

## 计算口径摘要

- 北上/南下资金：使用 TuShare `moneyflow_hsgt` 当日净额字段，万元折算为亿元后按窗口累加。
- ETF 净申购金额：使用 `fund_share.fd_share` 相邻交易日份额差，优先乘以同日 `fund_nav.unit_nav`；同日净值缺失时回退 `fund_daily.close`。
- 当日 ETF 规模：使用最新份额乘以最新收盘价估算。
- 当日涨跌幅：按最新收盘价相对窗口上一交易日收盘价计算，并按规模加权聚合。
- 宽基被动 ETF：要求跟踪基准明确匹配宽基指数，且宽基匹配时要求 `invest_type = 被动指数型`。
- 行业和策略因子：优先按 `fund_basic.benchmark` 跟踪指数归类，不靠基金简称做主观分类。

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
