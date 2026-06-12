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

- `window=1d|3d|7d|30d`：选择页面主窗口；返回体仍包含全部窗口的总览数据。
- `refresh=1`：跳过进程内短缓存，强制重新拉取数据。

## 后端模块

| 文件 | 职责 |
|---|---|
| `src/app.py` | Flask app 入口，注册资金流向路由 |
| `src/config_loader.py` | 从环境变量和 `.env.local` 读取配置 |
| `src/http_client.py` | 标准库 HTTP JSON 请求封装 |
| `src/tushare_client.py` | TuShare Pro 最小客户端，统一错误处理 |
| `src/capital_flow/routes.py` | 页面路由和 API 路由 |
| `src/capital_flow/service.py` | 缓存、窗口选择、TuShare 拉取编排、payload 校验 |
| `src/capital_flow/fetcher.py` | 按接口封装 TuShare 数据读取 |
| `src/capital_flow/calculator.py` | 北上/南下资金、ETF 净申购、规模、涨跌幅计算 |
| `src/capital_flow/taxonomy.py` | 宽基、策略因子、A 股行业、港股行业分类规则 |
| `src/capital_flow/schema.py` | API 返回结构校验，防止前后端契约漂移 |

## 前端模块

| 文件 | 职责 |
|---|---|
| `src/templates/capital_flow.html` | 首页模板和基础 DOM 容器 |
| `src/static/capital_flow.js` | API 请求、总览矩阵、表格渲染、排序、展开曲线 |
| `src/static/capital_flow.css` | 页面布局、表格、颜色和响应式样式 |

前端不直接保存用户配置，也不写入后端数据。刷新页面或调用 API 会重新读取后端缓存或 TuShare 数据。

## 缓存

`src/capital_flow/service.py` 中 `ETF_CACHE_SECONDS = 30 * 60`。

- 缓存按窗口 key 保存。
- 默认 API 请求会使用缓存。
- `refresh=1` 会强制刷新。
- 缓存只在当前 Python 进程内存在，服务重启后清空。

## API 返回结构

顶层主要字段：

- `north_south`：当前窗口北上/南下资金。
- `etf`：当前窗口 ETF 数据，包括 `sections`、`coverage`、`quality`。
- `window_payloads`：`1d / 3d / 7d / 30d` 全部窗口数据，用于总览矩阵。
- `windows`：窗口配置。
- `default_window`：默认窗口，当前为 `1d`。
- `selected_window` / `selected_window_label`：当前窗口。
- `threshold_yi`：行业和策略因子的规模展示阈值，当前为 `20`。
- `notes`：页面口径提示。

`etf.sections` 下的 section：

- `broad`：宽基被动 ETF。
- `strategy`：策略因子 ETF。
- `a_industry`：A 股行业 ETF。
- `hk_industry`：港股行业 ETF。

## 测试

| 测试文件 | 覆盖内容 |
|---|---|
| `tests/test_capital_flow_service.py` | TuShare 数据样本、计算口径、分类规则、payload 结构 |
| `tests/test_capital_flow_ui_contract.py` | 前端脚本关键契约、字段名、默认排序 |

统一验证入口：

```bash
scripts/verify_all.sh
```

## 变更建议

- 修改计算口径时，先加或改 `tests/test_capital_flow_service.py`。
- 修改 API 字段时，必须同步 `schema.py` 和前端渲染逻辑。
- 修改分类规则时，优先在 `taxonomy.py` 增加明确的跟踪指数映射；不要仅凭基金简称做高风险主观归类。
- 修改页面布局时，至少运行 `node --check src/static/capital_flow.js` 和完整 `scripts/verify_all.sh`。
