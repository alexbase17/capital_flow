# 运维说明

更新时间：2026-06-13

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

## 访问验证

页面：

```bash
curl --noproxy '*' -sS -o /tmp/capital_flow.html -w '%{http_code}\n' http://127.0.0.1:5083/
curl --noproxy '*' -sS -o /tmp/capital_flow_lan.html -w '%{http_code}\n' http://192.168.5.6:5083/
```

API：

```bash
curl --noproxy '*' -sS -o /tmp/capital_flow.json -w '%{http_code}\n' http://127.0.0.1:5083/api/capital-flow
```

期望 HTTP 状态码均为 `200`。API 首次请求可能需要等待 TuShare 返回数据。

## 项目验证

```bash
scripts/verify_all.sh
```

验证包含：

- Python 单元测试。
- Python 编译检查。
- `node --check src/static/capital_flow.js`。
- Git whitespace 检查。

如果当前项目 `.venv` 不可用，也可以复用家庭资产项目虚拟环境：

```bash
PYTHON_BIN=/Users/nova/workspace/data_forge_ws/.venv/bin/python scripts/verify_all.sh
```

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

### 修改分类后和机构数据仍有差异

这是预期风险之一。机构可能使用 Wind 自有 ETF 池、公告日/确认日、场内/场外分层或人工维护分类。本项目当前以 TuShare ETF 数据和跟踪指数规则为准，目标是方向参考和可解释，不保证逐项贴合某一家机构。

## 提交流程

1. 修改代码或文档。
2. 运行 `scripts/verify_all.sh`。
3. 更新 `docs/changelog.md`。
4. `git status --short` 确认变更。
5. `git add ... && git commit ... && git push`。
