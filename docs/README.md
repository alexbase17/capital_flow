# 文档索引

更新时间：2026-06-13

## 新 session 阅读顺序

1. 先读项目根目录 [README.md](../README.md)，确认项目边界、启动方式和验证命令。
2. 再读 [architecture.md](architecture.md)，理解后端模块、前端模块和请求链路。
3. 涉及计算或口径变更时，读 [data_sources.md](data_sources.md)。
4. 涉及启动、端口、局域网访问、后台服务或故障排查时，读 [operations.md](operations.md)。
5. 提交前更新 [changelog.md](changelog.md)。

## 文件说明

- `architecture.md`：代码结构、模块职责、请求链路、与家庭资产项目的隔离边界。
- `operations.md`：启动、LaunchAgent、配置、验证、常见问题。
- `data_sources.md`：TuShare 接口、字段含义、ETF 净申购和分类口径。
- `changelog.md`：按日期记录重要功能、口径和运维变更。

## 维护原则

- 本项目只做市场资金流向，不接入个人投资数据库。
- 计算口径变更必须同步更新 `data_sources.md` 和测试。
- 服务、端口、环境变量、后台启动方式变更必须同步更新 `operations.md`。
- 新增页面字段或 API 字段时，同步更新 `README.md`、`architecture.md` 或 `data_sources.md` 中对应说明。
