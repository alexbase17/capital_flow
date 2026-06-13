function windowPayload(data, key) {
  return data?.window_payloads?.[key] || {};
}

function sectionRows(data, key, sectionKey) {
  return windowPayload(data, key)?.etf?.sections?.[sectionKey]?.rows || [];
}

function hsgtValue(data, key, name) {
  const row = (windowPayload(data, key)?.north_south?.rows || []).find(item => item.name === name);
  return Number(row?.net_change_yi || 0);
}

function sectionValue(data, key, sectionKey) {
  return sumBy(sectionRows(data, key, sectionKey), "net_flow_yi");
}

function sectionTurnoverRatio(data, key, sectionKey) {
  const rows = sectionRows(data, key, sectionKey).filter(row => row.turnover_ratio !== null && row.turnover_ratio !== undefined);
  const dailyTotals = new Map();
  rows.forEach(row => {
    (row.daily_turnover || []).forEach(point => {
      const current = dailyTotals.get(point.date) || { turnover: 0, startScale: 0 };
      current.turnover += Number(point.value || 0);
      current.startScale += Number(point.start_scale_yi || 0);
      dailyTotals.set(point.date, current);
    });
  });
  const ratios = [...dailyTotals.values()]
    .filter(point => point.startScale > 0)
    .map(point => point.turnover / point.startScale * 100);
  if (ratios.length) return ratios.reduce((total, value) => total + value, 0) / ratios.length;
  const startScale = sumBy(rows, "start_scale_yi");
  return startScale ? rows.reduce((total, row) => total + Number(row.turnover_ratio || 0) * Number(row.start_scale_yi || 0), 0) / startScale : null;
}

function rowKey(row) {
  return `${row.index_name || ""}|${row.index_code || ""}`;
}

function mergeRowsForSection(data, sectionKey) {
  const rowsByKey = new Map();
  windowKeys.forEach(key => {
    sectionRows(data, key, sectionKey).forEach(row => {
      const keyValue = rowKey(row);
      const current = rowsByKey.get(keyValue) || {
        index_name: row.index_name,
        display_name: row.display_name,
        index_code: row.index_code,
        etf_count: row.etf_count,
        metrics: {}
      };
      current.display_name = current.display_name || row.display_name;
      current.index_code = current.index_code || row.index_code;
      current.etf_count = row.etf_count ?? current.etf_count;
      current.metrics[key] = {
        change_pct: row.change_pct,
        net_flow_yi: row.net_flow_yi,
        net_flow_ratio: row.net_flow_ratio,
        turnover_ratio: row.turnover_ratio,
        scale_yi: row.scale_yi,
        start_scale_yi: row.start_scale_yi,
        daily_net_flow: row.daily_net_flow || [],
        daily_change_pct: row.daily_change_pct || [],
        daily_turnover: row.daily_turnover || []
      };
      if (key === "1d") current.change_pct = row.change_pct;
      if (key === "5d") current.turnover_5d = row.turnover_ratio;
      if (key === "60d") {
        current.daily_net_flow = row.daily_net_flow || [];
        current.daily_change_pct = row.daily_change_pct || [];
        current.daily_turnover = row.daily_turnover || [];
      }
      rowsByKey.set(keyValue, current);
    });
  });
  return [...rowsByKey.values()].map(row => ({
    ...row,
    change_pct: row.metrics["1d"]?.change_pct ?? row.change_pct ?? null,
    ...Object.fromEntries(windowKeys.flatMap(key => [
      [`flow_${key}`, row.metrics[key]?.net_flow_yi ?? 0],
      [`ratio_${key}`, row.metrics[key]?.net_flow_ratio ?? null]
    ])),
    scale_yi: row.metrics["1d"]?.scale_yi ?? row.metrics["60d"]?.scale_yi ?? 0,
    turnover_5d: row.metrics["5d"]?.turnover_ratio ?? row.turnover_5d ?? null,
    daily_net_flow: row.metrics["60d"]?.daily_net_flow || row.daily_net_flow || [],
    daily_change_pct: row.metrics["60d"]?.daily_change_pct || row.daily_change_pct || [],
    daily_turnover: row.metrics["60d"]?.daily_turnover || row.daily_turnover || []
  }));
}
