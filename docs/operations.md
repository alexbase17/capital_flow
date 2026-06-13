# 运维说明

更新时间：2026-06-14

## 定位

本项目是独立的市场资金流向看板，只读调用 TuShare，不连接家庭资产项目的 `portfolio.db`，不参与个人投资收益计算。

## 本地环境

项目目录：

```text
/Users/nova/workspace/capital_flow_ws
```

推荐 Python：

```text
/Users/nova/workspace/capital_flow_ws/.venv/bin/python
```

如果需要重建虚拟环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

当前 `requirements.txt` 只依赖 Flask。TuShare 调用使用项目内的标准库 HTTP client，不依赖官方 SDK。

## 配置

本地配置文件：

```text
.env.local
```

该文件不提交 Git，当前只需要：

```env
TUSHARE_TOKEN=你的TuShareToken
DEEPSEEK_API_KEY=可选DeepSeekKey
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_TIMEOUT_SECONDS=30
```

安全要求：

- 不要把 `.env.local`、token、日志中的敏感信息提交到 Git。
- 文档中只写变量名，不写真实 token。

## 前台启动

```bash
scripts/start_web.sh
```

默认：

```text
Host: 0.0.0.0
Port: 5083
Local: http://127.0.0.1:5083/
LAN: http://192.168.5.6:5083/
```

可临时指定端口：

```bash
PORT=5090 HOST=127.0.0.1 scripts/start_web.sh
```

## 后台服务

当前使用 macOS LaunchAgent 托管：

```text
/Users/nova/Library/LaunchAgents/com.capital-flow.web.plist
```

服务配置要点：

```text
Label: com.capital-flow.web
WorkingDirectory: /Users/nova/workspace/capital_flow_ws
HOST: 0.0.0.0
PORT: 5083
VENV_DIR: .venv
stdout: /Users/nova/workspace/capital_flow_ws/logs/web.log
stderr: /Users/nova/workspace/capital_flow_ws/logs/web.err.log
```

检查服务：

```bash
launchctl print gui/$(id -u)/com.capital-flow.web
lsof -nP -iTCP:5083 -sTCP:LISTEN
```

期望监听结果包含：

```text
TCP *:5083 (LISTEN)
```

如果显示 `127.0.0.1:5083`，局域网其他电脑无法访问，需要把 LaunchAgent 中 `HOST` 改为 `0.0.0.0` 后重启服务。

重启服务：

```bash
launchctl bootout gui/$(id -u) /Users/nova/Library/LaunchAgents/com.capital-flow.web.plist
launchctl bootstrap gui/$(id -u) /Users/nova/Library/LaunchAgents/com.capital-flow.web.plist
```

仅需要重启当前运行实例时：

```bash
scripts/restart_web.sh
```

修改 `src/templates/` 或 `src/static/` 后，后台服务需要重启或 kickstart。Flask 生产模式下可能继续使用旧模板缓存；如果只更新了 CSS/JS 而模板仍旧，页面会出现旧 DOM 与新样式混用的问题。

## 访问验证

页面：

```bash
scripts/check_web.sh
```

`scripts/check_web.sh` 默认验证首页和主数据 API，并显式禁用本机代理，避免代理配置干扰 localhost 探活。默认地址为 `http://127.0.0.1:5083`，可用 `BASE_URL` 覆盖：

```bash
BASE_URL=http://192.168.5.6:5083 scripts/check_web.sh
```

期望 HTTP 状态码均为 `200`。成功生成的主 payload 会落盘缓存；服务重启后若 12 小时内存在上次成功 payload，API 会先快速返回缓存并在页面状态栏提示“使用上次成功缓存”。如果后续 TuShare 短时限流或网络失败，API 也会返回上次成功 payload，避免整页空白。

页面静态资源烟测：

```bash
.venv/bin/python scripts/verify_dashboard_page.py http://127.0.0.1:5083
```

该脚本会验证首页 HTML 引入了全部拆分后的 `capital_flow*.js`，脚本顺序正确，入口 JS 只初始化一次，静态资源和 `/api/capital-flow` 均可访问。修改模板、JS 拆分、启动脚本或遇到“页面只有标题/加载失败”时必须运行。

AI 摘要单独验证：

```bash
CHECK_AI_SUMMARY=1 scripts/check_web.sh
```

`/api/capital-flow` 不同步等待 DeepSeek，只返回核心表格数据和隐藏摘要占位；`/api/capital-flow/ai-summary` 会在主表加载后单独调用 DeepSeek，默认等待 30 秒。若 DeepSeek key、余额、网络或模型名异常，页面会隐藏 AI 总结模块，表格不应空白。

AI 摘要成功返回后会按数据版本缓存 24 小时；同一份资金流摘要输入、同一模型和同一版 prompt 反复打开页面不会重复请求 DeepSeek。若底层数据更新、模型或 prompt 变化，会自动重新请求。需要人工强刷时使用：

```bash
curl --noproxy '*' -sS -o /tmp/capital_flow_ai_summary.json -w '%{http_code}\n' 'http://127.0.0.1:5083/api/capital-flow/ai-summary?refresh=1'
```

## 项目验证

日常快速验证：

```bash
scripts/verify_fast.sh
```

提交或上线前完整验证：

```bash
scripts/verify_all.sh
```

`verify_fast.sh` 包含：

- Python 单元测试。
- `node --check src/static/capital_flow*.js`，覆盖资金流前端全部 JS 模块。
- Git whitespace 检查。

`verify_all.sh` 额外包含 Python 编译检查和 `scripts/validate_taxonomy_data.py` 分类主数据校验。

分类主数据单独校验：

```bash
scripts/validate_taxonomy_data.py
scripts/validate_taxonomy_data.py --audit --sample-limit 5
```

资金流快照审计：

```bash
scripts/audit_capital_flow_snapshot.py --max-items 12
```

该脚本读取最近成功的 `capital_flow_payload` 缓存，输出 stale 缓存、NAV 估算占比、跳过流量点、分类覆盖率和大额/高占比/高成交均值占比异常行。默认会把完整审计 JSON 写入：

```text
logs/audits/capital_flow_snapshot/
```

如只想临时查看、不落盘，可加 `--no-write-log`。默认 warning 不会阻断服务；上线前如希望发现 warning 即失败，可加 `--fail-on-warning`。

`scripts/start_web.sh`、`scripts/verify_fast.sh` 和 `scripts/verify_all.sh` 共享 `scripts/lib_env.sh`：

- 默认使用本项目 `.venv`。
- 如果默认 `.venv` 损坏，会自动用 `python3 -m venv --clear .venv` 重建。
- `requirements.txt` 未变化时跳过 `pip install`，减少启动和测试耗时。
- 统一设置 `PYTHONPYCACHEPREFIX=/tmp/capital_flow_pycache`，避免 macOS 系统 Python 把编译缓存写到受限目录。
- 如确实需要使用外部解释器，可显式传入 `PYTHON_BIN=/path/to/python scripts/verify_all.sh`；外部解释器不可用时脚本会直接失败，不会自动清理外部环境。

## 日志

后台服务日志：

```text
logs/web.log
logs/web.err.log
```

常用查看：

```bash
tail -100 logs/web.log
tail -100 logs/web.err.log
```

服务会输出 `capital_flow` 结构化 JSON 事件，当前覆盖：

- `capital_flow_payload_memory_cache_hit`
- `capital_flow_payload_disk_cache_hit`
- `capital_flow_payload_stale_cache_used`
- `capital_flow_payload_built`

这些事件用于排查页面是否命中缓存、是否因 TuShare 或网络问题使用上次成功 payload，以及本次构建的数据日和 NAV 估算占比。

## 数据缓存

TuShare 原始响应缓存目录：

```text
data/tushare_cache/
```

用途：

- 避免服务重启或 API payload 缓存过期后重复拉取完整 60 个交易日窗口。
- 日常使用时主要补新增交易日数据，历史日期直接复用本地缓存。
- 近期交易日缓存 30 分钟，历史交易日长期复用。

排障时绕过文件缓存：

```bash
CAPITAL_FLOW_DISABLE_FILE_CACHE=1 scripts/start_web.sh
```

如果怀疑本地缓存损坏，可以删除 `data/tushare_cache/` 后重启服务；首次请求会重新拉取完整窗口，耗时会明显变长。

## 常见问题

### 本机能访问，局域网不能访问

检查监听地址：

```bash
lsof -nP -iTCP:5083 -sTCP:LISTEN
```

- `127.0.0.1:5083`：只允许本机访问，改 LaunchAgent 的 `HOST` 为 `0.0.0.0`。
- `*:5083`：服务已监听所有网卡，再检查对方电脑是否在同一局域网、macOS 防火墙或路由隔离。

### API 返回 502

常见原因：

- `.env.local` 缺少 `TUSHARE_TOKEN`。
- TuShare token 无权限访问对应接口。
- TuShare 接口短时失败或网络失败。

检查：

```bash
cat logs/web.err.log
curl --noproxy '*' -sS http://127.0.0.1:5083/api/capital-flow
```

### 页面打开但表格为空

可能原因：

- TuShare 当日数据尚未更新。
- 近期交易日数据不足。
- 分类规则没有匹配到对应 ETF 的 `benchmark`。
- 行业、港股行业、策略因子主题规模低于 20 亿元展示阈值。

排查优先看 API JSON 中的：

- `etf.coverage`
- `etf.quality`
- `etf.sections`

当外部数据刷新失败或服务 warm start 使用上次成功 payload 时，`payload_cache_status=stale`
会同步写入顶层、当前窗口和全部 `window_payloads` 的 ETF `data_status`。后台审计和 AI
摘要输入都应把该状态视为缓存兜底数据，不能当作本次已成功刷新的最新结果。

### AI 总结不显示

可能原因：

- `.env.local` 未配置 `DEEPSEEK_API_KEY`。
- DeepSeek 余额、权限、网络或限流异常。
- 模型返回非 JSON 或字段不完整，后端返回隐藏摘要占位。
- 资金流向 payload 使用缓存兜底时，AI 输入会携带 `quality.payload_cache_status=stale`，
  模型应按上次成功数据解读。

检查：

```bash
.venv/bin/python -c "from src.config_loader import get_config; print(bool(get_config('DEEPSEEK_API_KEY')))"
curl --noproxy '*' -sS http://127.0.0.1:5083/api/capital-flow/ai-summary
```

配置或修改 `.env.local` 后需要重启服务：

```bash
launchctl kickstart -k gui/$(id -u)/com.capital-flow.web
```

### 修改分类后和机构数据仍有差异

这是预期风险之一。机构可能使用 Wind 自有 ETF 池、公告日/确认日、场内/场外分层或人工维护分类。本项目当前以 TuShare ETF 数据和跟踪指数规则为准，目标是方向参考和可解释，不保证逐项贴合某一家机构。

分类改动后先运行后台审计：

```bash
.venv/bin/python scripts/audit_etf_taxonomy.py
```

涉及 A 股行业/主题边界时，再运行成分暴露审计：

```bash
.venv/bin/python scripts/audit_etf_taxonomy.py --with-sw-exposure --exposure-limit 30
```

重点看：

- `by_source.benchmark_exact` 是否提升，表示更多 ETF 使用明确指数映射。
- `by_source.benchmark_pattern` 是否下降，表示关键词兜底减少。
- `summary.coverage_pct` 使用前台可聚合目标为分母；`summary.raw_coverage_pct` 使用广义权益目标为分母。两者差异主要来自指数增强等不进入前台聚合的目标。
- `non_frontend_target_samples` 应主要是指数增强等已识别但不纳入宽基被动/行业/策略表的 ETF，不应混入普通被动行业或宽基 ETF。
- `by_taxonomy_type` 和 `by_parent_bucket` 是否符合预期，用于观察行业、主题、策略和后台大类结构。
- `unclassified_samples` 是否主要是区域、ESG、低碳、碳中和、新材料等需要成分暴露复核的主题；不要为了追求覆盖率，把无法确认的主题仅凭基金简称并入行业表。
- `sw2021_exposure.exposures` 中 `top_industry_weight` 是否足够集中；主题指数如果前三大行业分散，应保留主题分类，不硬并入单一传统行业。
- `sw2021_exposure.missing_index_code_samples` 会按当前 ETF 规模优先展示，先补 `scale_yi` 大、`etf_count` 多且能唯一确认的指数代码。
- `sw2021_exposure.label_consistency.flagged_samples` 是否提示同一前台标签下的跟踪指数暴露差异过大；这类结果先人工复核，不自动拆分前台标签。
- `sw2021_exposure.missing_index_code_count` 和 `no_weight_count` 是否异常升高；升高时先查指数代码解析或 TuShare 权重数据，不直接改前台标签。
- 精确映射应优先维护在 `src/capital_flow/taxonomy_data.json`；不要为了追求覆盖率，把无法确认的主题仅凭基金简称并入行业表。

## 提交流程

1. 修改代码或文档。
2. 运行 `scripts/verify_all.sh`。
3. 更新 `docs/changelog.md`。
4. `git status --short` 确认变更。
5. `git add ... && git commit ... && git push`。
