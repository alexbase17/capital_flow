const pctFmt = new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const yiFmtByDigits = {
  0: new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 0, maximumFractionDigits: 0 }),
  1: new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
  2: new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
};
const sectionIds = ["total", "broad", "a_industry", "hk_industry", "strategy"];
const windowKeys = ["1d", "5d", "20d", "60d"];
const windowLabels = { "1d": "1日", "5d": "5日", "20d": "20日", "60d": "60日" };
const windowTradeLabels = { "1d": "近1个交易日", "5d": "近5个交易日", "20d": "近20个交易日", "60d": "近60个交易日" };
const tableSortState = {};
const defaultTableSort = { key: "flow_1d", order: "desc" };
let latestCapitalFlowData = null;
let expandedRows = {};
