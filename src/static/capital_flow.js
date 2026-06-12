const moneyFmt = new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const sectionIds = ["total", "broad", "strategy", "a_industry", "hk_industry"];
const windowKeys = ["1d", "3d", "7d", "30d"];
const windowLabels = { "1d": "1日", "3d": "3日", "7d": "7日", "30d": "30日" };
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

function renderTotalFlow(data) {
  const wrap = document.getElementById("totalFlowCards");
  const columns = [
    ["北上资金", key => hsgtValue(data, key, "北上资金")],
    ["南下资金", key => hsgtValue(data, key, "南下资金")],
    ["宽基被动ETF", key => sectionValue(data, key, "broad")],
    ["策略因子(>=20亿)", key => sectionValue(data, key, "strategy")],
    ["A股行业(>=20亿)", key => sectionValue(data, key, "a_industry")],
    ["港股行业(>=20亿)", key => sectionValue(data, key, "hk_industry")]
  ];
  wrap.innerHTML = `
    <div class="flow-matrix" role="table" aria-label="ETF净申购金额">
      <div class="flow-matrix-head" role="row">
        <div role="columnheader">窗口</div>
        ${columns.map(([title]) => `<div role="columnheader">${title}</div>`).join("")}
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
        daily_net_flow: row.daily_net_flow || []
      };
      if (key === "1d") current.change_pct = row.change_pct;
      if (key === "30d") current.daily_net_flow = row.daily_net_flow || [];
      rowsByKey.set(keyValue, current);
    });
  });
  return [...rowsByKey.values()].map(row => ({
    ...row,
    change_pct: row.metrics["1d"]?.change_pct ?? row.change_pct ?? null,
    flow_1d: row.metrics["1d"]?.net_flow_yi ?? 0,
    flow_3d: row.metrics["3d"]?.net_flow_yi ?? 0,
    flow_7d: row.metrics["7d"]?.net_flow_yi ?? 0,
    flow_30d: row.metrics["30d"]?.net_flow_yi ?? 0,
    ratio_1d: row.metrics["1d"]?.net_flow_ratio ?? null,
    ratio_3d: row.metrics["3d"]?.net_flow_ratio ?? null,
    ratio_7d: row.metrics["7d"]?.net_flow_ratio ?? null,
    ratio_30d: row.metrics["30d"]?.net_flow_ratio ?? null,
    scale_yi: row.metrics["1d"]?.scale_yi ?? row.metrics["30d"]?.scale_yi ?? 0,
    daily_net_flow: row.metrics["30d"]?.daily_net_flow || row.daily_net_flow || []
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

function chartPath(points, width, height) {
  if (points.length < 2) return "";
  const values = points.map(point => Number(point.value || 0));
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const span = max - min || 1;
  return points.map((point, index) => {
    const x = points.length === 1 ? 0 : (index / (points.length - 1)) * width;
    const y = height - ((Number(point.value || 0) - min) / span) * height;
    return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

function renderFlowChart(row) {
  const points = row.daily_net_flow || [];
  if (!points.length) return '<div class="empty">暂无30日曲线数据</div>';
  const width = 760;
  const height = 150;
  const path = chartPath(points, width, height);
  const values = points.map(point => Number(point.value || 0));
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const zeroY = height - ((0 - min) / ((max - min) || 1)) * height;
  return `
    <div class="flow-chart">
      <div class="chart-title">30日净申购金额曲线</div>
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${formatIndexName(row)} 30日净申购金额曲线">
        <line x1="0" y1="${zeroY.toFixed(1)}" x2="${width}" y2="${zeroY.toFixed(1)}" class="zero-line"></line>
        <path d="${path}" class="flow-line"></path>
      </svg>
      <div class="chart-range">
        <span>${points[0]?.date || ""}</span>
        <span>${points[points.length - 1]?.date || ""}</span>
      </div>
    </div>
  `;
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
  table.innerHTML = `
    <thead>
      <tr>
        <th>指数 / 主题</th>
        <th class="num-head">${sortableHeader(tableId, "change_pct", "当日涨跌幅", "当日涨跌幅为该指数或主题下 ETF 最新交易日相对上一交易日的规模加权涨跌幅。")}</th>
        ${windowKeys.map(key => `<th class="num-head">${sortableHeader(tableId, `flow_${key}`, `${windowLabels[key]}净申购金额`, "按窗口内每日 ETF 份额日期相邻差逐日乘以同日单位净值后累加；同日净值缺失时用当日收盘价估算。正数表示净申购，负数表示净赎回。")}</th>`).join("")}
        ${windowKeys.map(key => `<th class="num-head">${sortableHeader(tableId, `ratio_${key}`, `${windowLabels[key]}净申购金额占比`, "净申购金额占比 = 对应窗口净申购金额 / 当日 ETF 规模。")}</th>`).join("")}
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
            ${metricCell(row.flow_1d)}
            ${metricCell(row.flow_3d)}
            ${metricCell(row.flow_7d)}
            ${metricCell(row.flow_30d)}
            ${metricCell(row.ratio_1d, fmtPct)}
            ${metricCell(row.ratio_3d, fmtPct)}
            ${metricCell(row.ratio_7d, fmtPct)}
            ${metricCell(row.ratio_30d, fmtPct)}
            <td class="num">${fmtYi(row.scale_yi)}</td>
          </tr>
          ${expanded ? `<tr class="detail-row"><td colspan="11">${renderFlowChart(row)}</td></tr>` : ""}
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
  renderTotalFlow(data);
  renderTable("broadTable", "broad");
  renderTable("strategyTable", "strategy");
  renderTable("aIndustryTable", "a_industry");
  renderTable("hkIndustryTable", "hk_industry");
}

loadCapitalFlow();
setupSectionNav();
