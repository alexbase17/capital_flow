const moneyFmt = new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const sectionIds = ["total", "broad", "a_industry", "hk_industry", "strategy"];
const windowKeys = ["1d", "3d", "5d", "20d", "60d"];
const windowLabels = { "1d": "1日", "3d": "3日", "5d": "5日", "20d": "20日", "60d": "60日" };
const tableSortState = {};
const defaultTableSort = { key: "flow_1d", order: "desc" };
let latestCapitalFlowData = null;
let expandedRows = {};

function flowClass(value) {
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "neutral";
}

function fmtYi(value) {
  return `${moneyFmt.format(Number(value || 0))} 亿`;
}

function fmtPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return `${moneyFmt.format(Number(value))}%`;
}

function formatIndexName(row) {
  const name = row.display_name || row.index_name;
  return row.index_code ? `${name}（${row.index_code}）` : name;
}

function sumBy(rows, key) {
  return (rows || []).reduce((total, row) => total + Number(row?.[key] || 0), 0);
}

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
  const turnover = sumBy(rows, "turnover_yi");
  const startScale = sumBy(rows, "start_scale_yi");
  return startScale ? turnover / startScale * 100 : null;
}

function renderTotalFlow(data) {
  const wrap = document.getElementById("totalFlowCards");
  const columns = [
    ["北上资金", key => hsgtValue(data, key, "北上资金")],
    ["南下资金", key => hsgtValue(data, key, "南下资金")],
    ["宽基被动ETF", key => sectionValue(data, key, "broad")],
    ["A股行业(>=20亿)", key => sectionValue(data, key, "a_industry")],
    ["港股行业(>=20亿)", key => sectionValue(data, key, "hk_industry")],
    ["策略因子(>=20亿)", key => sectionValue(data, key, "strategy")]
  ];
  wrap.innerHTML = `
    <div class="flow-matrix" role="table" aria-label="ETF净申购金额">
      <div class="flow-matrix-head" role="row">
        <div role="columnheader">指标</div>
        ${columns.map(([title]) => `<div role="columnheader">${title}</div>`).join("")}
      </div>
      <div class="flow-matrix-row" role="row">
        <div class="window-cell" role="cell">5日成交额占比</div>
        <div class="matrix-value muted" role="cell">--</div>
        <div class="matrix-value muted" role="cell">--</div>
        ${["broad", "a_industry", "hk_industry", "strategy"].map(sectionKey => {
          const value = sectionTurnoverRatio(data, "5d", sectionKey);
          return `<div class="matrix-value neutral" role="cell">${fmtPct(value)}</div>`;
        }).join("")}
      </div>
      ${windowKeys.map(key => `
        <div class="flow-matrix-row" role="row">
          <div class="window-cell" role="cell">${windowLabels[key]}</div>
          ${columns.map(([, getter]) => {
            const value = getter(key);
            return `<div class="matrix-value ${flowClass(value)}" role="cell">${fmtYi(value)}</div>`;
          }).join("")}
        </div>
      `).join("")}
    </div>
  `;
}

function renderDataStatus(data) {
  const el = document.getElementById("dataStatus");
  if (!el) return;
  const status = data?.data_status?.etf || data?.etf?.data_status;
  if (!status) {
    el.textContent = "";
    el.className = "data-status";
    return;
  }
  const parts = [
    `ETF数据日 ${status.as_of_date || "--"}`,
    `价格日 ${status.price_date || "--"}`,
    `份额日 ${status.share_date || "--"}`,
    `净值日 ${status.nav_date || "收盘价估算"}`
  ];
  if (status.status === "fallback") {
    parts.push("已回退到最近完整交易日");
  }
  el.textContent = parts.join(" · ");
  el.className = `data-status${status.status === "fallback" ? " warning" : ""}`;
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

function sortableHeader(tableId, key, label, help = "") {
  const state = tableSortState[tableId] || defaultTableSort;
  const active = state.key === key;
  const order = active ? state.order : "desc";
  const nextOrder = active && order === "desc" ? "asc" : "desc";
  const helpTip = help ? ` <span class="help-tip" tabindex="0" aria-label="${help}">?</span>` : "";
  return `<button class="sort-button${active ? " active" : ""}" data-sort-key="${key}" data-next-order="${nextOrder}"${active ? ` data-sort-order="${order}"` : ""} type="button">${label}</button>${helpTip}`;
}

function sortedRows(tableId, rows) {
  const state = tableSortState[tableId] || defaultTableSort;
  const direction = state.order === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = Number(a?.[state.key]);
    const bv = Number(b?.[state.key]);
    const aMissing = Number.isNaN(av);
    const bMissing = Number.isNaN(bv);
    if (aMissing && bMissing) return 0;
    if (aMissing) return 1;
    if (bMissing) return -1;
    return (av - bv) * direction;
  });
}

function bindTableSort(tableId, sectionKey) {
  const table = document.getElementById(tableId);
  table.querySelectorAll("[data-sort-key]").forEach(button => {
    button.addEventListener("click", event => {
      event.stopPropagation();
      const key = button.dataset.sortKey;
      const current = tableSortState[tableId];
      const order = current?.key === key && current.order === "desc" ? "asc" : "desc";
      tableSortState[tableId] = { key, order };
      renderTable(tableId, sectionKey);
    });
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function chartDomain(points) {
  const values = points.map(point => Number(point.value || 0));
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const span = max - min || 1;
  return { min, max, span };
}

function chartPath(points, width, height) {
  if (points.length < 2) return "";
  const { min, span } = chartDomain(points);
  return points.map((point, index) => {
    const x = points.length === 1 ? 0 : (index / (points.length - 1)) * width;
    const y = height - ((Number(point.value || 0) - min) / span) * height;
    return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

function rollingWindowPoints(points, windowSize = 5) {
  if (points.length < windowSize) return [];
  return points.slice(windowSize - 1).map((point, index) => {
    const windowPoints = points.slice(index, index + windowSize);
    const value = windowPoints.reduce((total, item) => total + Number(item.value || 0), 0);
    return {
      date: point.date,
      start_date: windowPoints[0]?.date || "",
      end_date: point.date,
      value
    };
  });
}

function rollingTurnoverRatioPoints(points, windowSize = 5) {
  if (points.length < windowSize) return [];
  return points.slice(windowSize - 1).map((point, index) => {
    const windowPoints = points.slice(index, index + windowSize);
    const value = windowPoints.reduce((total, item) => total + Number(item.value || 0), 0);
    const startScale = Number(windowPoints[0]?.start_scale_yi || 0);
    return {
      date: point.date,
      start_date: windowPoints[0]?.date || "",
      end_date: point.date,
      value: startScale > 0 ? value / startScale * 100 : null
    };
  }).filter(point => point.value !== null);
}

function tooltipPayload(value) {
  return escapeHtml(value);
}

function nearestTooltipIndex(ratio, items) {
  if (items.length <= 1) return 0;
  let bestIndex = 0;
  let bestDistance = Infinity;
  items.forEach((item, index) => {
    const fallbackX = items.length === 1 ? 0 : index / (items.length - 1);
    const x = Number.isFinite(Number(item.x)) ? Number(item.x) : fallbackX;
    const distance = Math.abs(x - ratio);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  });
  return bestIndex;
}

function renderDailyFlowBars(points, label) {
  const width = 1040;
  const height = 180;
  const plotTop = 10;
  const plotHeight = 150;
  const { min, span } = chartDomain(points);
  const zeroY = plotTop + plotHeight - ((0 - min) / span) * plotHeight;
  const slot = width / Math.max(points.length, 1);
  const barWidth = Math.max(3, Math.min(14, slot * 0.68));
  const bars = points.map((point, index) => {
    const value = Number(point.value || 0);
    const valueY = plotTop + plotHeight - ((value - min) / span) * plotHeight;
    const x = index * slot + (slot - barWidth) / 2;
    const y = Math.min(valueY, zeroY);
    const h = Math.max(1, Math.abs(zeroY - valueY));
    const className = value >= 0 ? "flow-bar positive-bar" : "flow-bar negative-bar";
    return `
      <rect class="${className}" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${h.toFixed(1)}"></rect>
    `;
  }).join("");
  const tooltipValues = points.map((point, index) => ({
    x: (index + 0.5) / Math.max(points.length, 1),
    date: point.date,
    label: `${point.date} · 净申购金额 ${fmtYi(point.value)}`
  }));
  return `
    <div class="flow-chart">
      <div class="chart-title" style="--zero-y: ${zeroY.toFixed(1)}px">${label}</div>
      <div class="flow-chart-body">
        <div class="flow-chart-plot" data-chart-tooltips='${tooltipPayload(JSON.stringify(tooltipValues))}'>
          <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(label)}">
            <line x1="0" y1="${zeroY.toFixed(1)}" x2="${width}" y2="${zeroY.toFixed(1)}" class="zero-line"></line>
            ${bars}
          </svg>
          <div class="chart-hover-layer" aria-hidden="true"></div>
          <div class="chart-tooltip" aria-hidden="true"></div>
        </div>
      </div>
    </div>
  `;
}

function renderDailyChangeLine(points, label) {
  if (!points.length) return '<div class="empty">暂无分天涨跌幅数据</div>';
  const width = 1040;
  const height = 180;
  const plotTop = 10;
  const plotHeight = 150;
  const { min, span } = chartDomain(points);
  const zeroY = plotTop + plotHeight - ((0 - min) / span) * plotHeight;
  const path = points.map((point, index) => {
    const x = points.length === 1 ? width / 2 : (index / (points.length - 1)) * width;
    const y = plotTop + plotHeight - ((Number(point.value || 0) - min) / span) * plotHeight;
    return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const dots = points.map((point, index) => {
    const x = points.length === 1 ? width / 2 : (index / (points.length - 1)) * width;
    const y = plotTop + plotHeight - ((Number(point.value || 0) - min) / span) * plotHeight;
    return `
      <circle class="rolling-point ${flowClass(point.value)}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4.2"></circle>
    `;
  }).join("");
  const tooltipValues = points.map((point, index) => ({
    x: points.length === 1 ? 0.5 : index / (points.length - 1),
    date: point.date,
    label: `${point.date} · 涨跌幅 ${fmtPct(point.value)}`
  }));
  return `
    <div class="flow-chart">
      <div class="chart-title" style="--zero-y: ${zeroY.toFixed(1)}px">${label}</div>
      <div class="flow-chart-body">
        <div class="flow-chart-plot" data-chart-tooltips='${tooltipPayload(JSON.stringify(tooltipValues))}'>
          <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(label)}">
            <line x1="0" y1="${zeroY.toFixed(1)}" x2="${width}" y2="${zeroY.toFixed(1)}" class="zero-line"></line>
            <path d="${path}" class="flow-line"></path>
            ${dots}
          </svg>
          <div class="chart-hover-layer" aria-hidden="true"></div>
          <div class="chart-tooltip" aria-hidden="true"></div>
        </div>
      </div>
    </div>
  `;
}

function renderLineChart(points, label, valueLabel, formatter = fmtYi) {
  if (!points.length) return '<div class="empty">暂无走势数据</div>';
  const width = 1040;
  const height = 180;
  const plotTop = 10;
  const plotHeight = 150;
  const { min, span } = chartDomain(points);
  const zeroY = plotTop + plotHeight - ((0 - min) / span) * plotHeight;
  const path = points.map((point, index) => {
    const x = points.length === 1 ? 0 : (index / (points.length - 1)) * width;
    const y = plotTop + plotHeight - ((Number(point.value || 0) - min) / span) * plotHeight;
    return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const dots = points.map((point, index) => {
    const x = points.length === 1 ? 0 : (index / (points.length - 1)) * width;
    const y = plotTop + plotHeight - ((Number(point.value || 0) - min) / span) * plotHeight;
    return `
      <circle class="rolling-point ${flowClass(point.value)}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4.6"></circle>
    `;
  }).join("");
  const tooltipValues = points.map((point, index) => ({
    x: points.length === 1 ? 0 : index / (points.length - 1),
    date: point.end_date || point.date,
    label: `${point.start_date} 至 ${point.end_date} · ${valueLabel} ${formatter(point.value)}`
  }));
  return `
    <div class="flow-chart">
      <div class="chart-title" style="--zero-y: ${zeroY.toFixed(1)}px">${label}</div>
      <div class="flow-chart-body">
        <div class="flow-chart-plot" data-chart-tooltips='${tooltipPayload(JSON.stringify(tooltipValues))}'>
          <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(label)}">
            <line x1="0" y1="${zeroY.toFixed(1)}" x2="${width}" y2="${zeroY.toFixed(1)}" class="zero-line"></line>
            <path d="${path}" class="flow-line"></path>
            ${dots}
          </svg>
          <div class="chart-hover-layer" aria-hidden="true"></div>
          <div class="chart-tooltip" aria-hidden="true"></div>
        </div>
      </div>
    </div>
  `;
}

function renderRollingFlowLine(points, label) {
  const rollingPoints = rollingWindowPoints(points, 5);
  if (!rollingPoints.length) return '<div class="empty">暂无5日滑动窗口数据</div>';
  return renderLineChart(rollingPoints, label, "净申购金额", fmtYi);
}

function renderRollingTurnoverRatioLine(points, label) {
  const rollingPoints = rollingTurnoverRatioPoints(points, 5);
  if (!rollingPoints.length) return '<div class="empty">暂无5日滑动成交额占比数据</div>';
  return renderLineChart(rollingPoints, label, "成交额占比", fmtPct);
}

function renderFlowChart(row) {
  const points = row.daily_net_flow || [];
  const changePoints = row.daily_change_pct || [];
  const turnoverPoints = row.daily_turnover || [];
  if (!points.length && !changePoints.length && !turnoverPoints.length) return '<div class="empty">暂无60日走势数据</div>';
  return `
    <div class="flow-chart-viewport">
      <div class="flow-chart-stack">
        ${renderDailyChangeLine(changePoints, "分天涨跌幅")}
        ${renderRollingTurnoverRatioLine(turnoverPoints, "5日滑动窗口成交额占比")}
        ${renderDailyFlowBars(points, "分天净申购金额")}
        ${renderRollingFlowLine(points, "5日滑动窗口净申购金额")}
      </div>
    </div>
  `;
}

function bindChartTooltips(scope) {
  scope.querySelectorAll("[data-chart-tooltips]").forEach(plot => {
    const tooltip = plot.querySelector(".chart-tooltip");
    let items = [];
    try {
      items = JSON.parse(plot.dataset.chartTooltips || "[]");
    } catch {
      items = [];
    }
    if (!tooltip || !items.length) return;
    plot.addEventListener("pointermove", event => {
      const rect = plot.getBoundingClientRect();
      const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
      const index = nearestTooltipIndex(ratio, items);
      const item = items[index] || {};
      const x = Math.min(0.98, Math.max(0.02, Number(item.x ?? ratio)));
      tooltip.textContent = item.label || "";
      tooltip.style.left = `${x * 100}%`;
      tooltip.classList.add("visible");
    });
    plot.addEventListener("pointerleave", () => {
      tooltip.classList.remove("visible");
    });
  });
}

function metricCell(value, formatter = fmtYi) {
  return `<td class="num ${flowClass(value)}">${formatter(value)}</td>`;
}

function renderTable(tableId, sectionKey) {
  const table = document.getElementById(tableId);
  const rows = mergeRowsForSection(latestCapitalFlowData, sectionKey);
  if (!rows.length) {
    table.innerHTML = '<tbody><tr><td class="empty">暂无数据</td></tr></tbody>';
    return;
  }
  const displayRows = sortedRows(tableId, rows);
  const columnCount = windowKeys.length * 2 + 4;
  table.innerHTML = `
    <thead>
      <tr>
        <th>指数 / 主题</th>
        <th class="num-head">${sortableHeader(tableId, "change_pct", "当日涨跌幅", "当日涨跌幅为该指数或主题下 ETF 最新交易日相对上一交易日的规模加权涨跌幅。")}</th>
        <th class="num-head">${sortableHeader(tableId, "turnover_5d", "5日成交额占比", "近5个交易日场内成交额合计 / 窗口期初 ETF 规模，用于观察二级市场交易热度，不等同于一级市场净申购资金流。")}</th>
        ${windowKeys.map(key => `<th class="num-head">${sortableHeader(tableId, `flow_${key}`, `${windowLabels[key]}净申购`, "按窗口内每日 ETF 份额日期相邻差逐日乘以同日单位净值后累加；同日净值缺失时用当日收盘价估算。正数表示净申购，负数表示净赎回。")}</th>`).join("")}
        ${windowKeys.map(key => `<th class="num-head">${sortableHeader(tableId, `ratio_${key}`, `${windowLabels[key]}净申购占比`, "净申购占比 = 对应窗口净申购金额 / 窗口期初 ETF 规模。期初规模按该窗口起点交易日的份额和收盘价估算，用于衡量资金流入强度。")}</th>`).join("")}
        <th class="num-head">${sortableHeader(tableId, "scale_yi", "当日ETF规模")}</th>
      </tr>
    </thead>
    <tbody>
      ${displayRows.map(row => {
        const key = rowKey(row);
        const expanded = Boolean(expandedRows[tableId]?.[key]);
        return `
          <tr class="data-row${expanded ? " expanded" : ""}" data-row-key="${key}" tabindex="0">
            <td class="name-cell"><span class="expand-mark">${expanded ? "−" : "+"}</span>${formatIndexName(row)}</td>
            ${metricCell(row.change_pct, fmtPct)}
            ${metricCell(row.turnover_5d, fmtPct)}
            ${windowKeys.map(key => metricCell(row[`flow_${key}`])).join("")}
            ${windowKeys.map(key => metricCell(row[`ratio_${key}`], fmtPct)).join("")}
            <td class="num">${fmtYi(row.scale_yi)}</td>
          </tr>
          ${expanded ? `<tr class="detail-row"><td colspan="${columnCount}">${renderFlowChart(row)}</td></tr>` : ""}
        `;
      }).join("")}
    </tbody>
  `;
  bindTableSort(tableId, sectionKey);
  table.querySelectorAll(".data-row").forEach(rowEl => {
    rowEl.addEventListener("click", () => toggleRow(tableId, sectionKey, rowEl.dataset.rowKey || ""));
    rowEl.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggleRow(tableId, sectionKey, rowEl.dataset.rowKey || "");
      }
    });
  });
  bindChartTooltips(table);
}

function toggleRow(tableId, sectionKey, key) {
  expandedRows[tableId] = expandedRows[tableId] || {};
  expandedRows[tableId][key] = !expandedRows[tableId][key];
  renderTable(tableId, sectionKey);
}

function setActiveSection(sectionId) {
  document.querySelectorAll("[data-section-link]").forEach(link => {
    link.classList.toggle("active", link.dataset.sectionLink === sectionId);
  });
}

function sectionFromHash(hash) {
  const targetId = String(hash || "").replace(/^#capital-section-/, "").replace(/-/g, "_");
  return sectionIds.includes(targetId) ? targetId : "total";
}

function pxVar(name, fallback) {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name);
  const parsed = Number.parseFloat(raw);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function activeSectionFromScroll(sections) {
  const anchorOffset = pxVar("--capital-header-height", 60) + pxVar("--capital-section-nav-height", 62) + 12;
  let active = sections[0]?.dataset?.section || "total";
  sections.forEach(section => {
    if (section.getBoundingClientRect().top <= anchorOffset) {
      active = section.dataset.section || active;
    }
  });
  return active;
}

function setupSectionNav() {
  document.querySelectorAll("[data-section-link]").forEach(link => {
    link.addEventListener("click", () => {
      setActiveSection(link.dataset.sectionLink || "total");
    });
  });

  setActiveSection(sectionFromHash(window.location.hash));

  const sections = sectionIds
    .map(id => document.querySelector(`[data-section="${id}"]`))
    .filter(Boolean);
  if (!sections.length) return;

  let ticking = false;
  const syncActiveSection = () => {
    ticking = false;
    setActiveSection(activeSectionFromScroll(sections));
  };
  const requestSync = () => {
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(syncActiveSection);
  };

  window.addEventListener("scroll", requestSync, { passive: true });
  window.addEventListener("hashchange", () => setActiveSection(sectionFromHash(window.location.hash)));
  requestSync();
}

async function loadCapitalFlow() {
  try {
    const response = await fetch("/api/capital-flow");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    latestCapitalFlowData = data;
    renderCapitalFlow(data);
  } catch (err) {
    console.error("资金流向加载失败", err);
    document.getElementById("totalFlowCards").innerHTML = `<div class="empty">资金流向加载失败：${err.message}</div>`;
  }
}

function renderCapitalFlow(data) {
  if (!data) return;
  renderDataStatus(data);
  renderTotalFlow(data);
  renderTable("broadTable", "broad");
  renderTable("aIndustryTable", "a_industry");
  renderTable("hkIndustryTable", "hk_industry");
  renderTable("strategyTable", "strategy");
}

loadCapitalFlow();
setupSectionNav();
