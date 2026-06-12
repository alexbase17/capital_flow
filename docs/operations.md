# 运维说明

更新时间：2026-06-13

## 定位

本项目是独立的市场资金流向看板，只读调用 TuShare，不连接家庭资产项目的 `portfolio.db`，不参与个人投资收益计算。

## 启动

```bash
scripts/start_web.sh
```

默认：

```text
Host: 0.0.0.0
Port: 5083
Local: http://127.0.0.1:5083/
```

## 配置

本地配置文件为 `.env.local`，不提交 Git。当前只需要 `TUSHARE_TOKEN`。

## 验证

```bash
scripts/verify_all.sh
```

验证包含单元测试、Python 编译检查、前端 JavaScript 语法检查和 whitespace 检查。
