# Capital Flow Dashboard

独立的市场资金流向看板。该项目只读调用 TuShare，不读取、不写入家庭资产数据库。

## 功能

- ETF 净申购金额总览：1日、3日、7日、30日窗口。
- 宽基被动 ETF、策略因子、A 股行业、港股行业明细表。
- 明细表展示当日涨跌幅、各窗口净申购金额、各窗口净申购金额占比和当日 ETF 规模。
- 点击明细行展开 30 日净申购金额曲线。

## 启动

```bash
scripts/start_web.sh
```

默认服务地址：

```text
http://127.0.0.1:5083/
```

局域网访问时使用本机内网 IP，例如：

```text
http://192.168.5.6:5083/
```

## 配置

`.env.local` 只需要：

```env
TUSHARE_TOKEN=你的TuShareToken
```

## 验证

```bash
scripts/verify_all.sh
```
