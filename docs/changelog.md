# 变更记录

## 2026-06-13

- 完善项目交接文档：扩展根目录 README，新增 `docs/architecture.md`，重写 `docs/operations.md` 和 `docs/data_sources.md`，补充项目边界、启动验证、LaunchAgent、局域网访问、TuShare 接口、ETF 净申购公式、分类规则、展示阈值和常见差异来源，方便后续新 session 接手。
- 从家庭资产项目拆出为独立资金流向项目。
- 独立服务默认运行在 `5083`，首页即资金流向页面。
- 项目只保留 TuShare 相关配置和资金流向计算，不读取家庭资产数据库。
