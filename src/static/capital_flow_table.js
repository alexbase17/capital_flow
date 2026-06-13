function sortableHeader(tableId, key, label, help = "") {
  const state = tableSortState[tableId] || defaultTableSort;
  const active = state.key === key;
  const order = active ? state.order : "desc";
  const nextOrder = active && order === "desc" ? "asc" : "desc";
  const helpTip = help ? ` <span class="help-tip" tabindex="0" aria-label="${help}">?</span>` : "";
  return `<button class="sort-button${active ? " active" : ""}" data-sort-key="${key}" data-next-order="${nextOrder}"${active ? ` data-sort-order="${order}"` : ""} type="button">${label}</button>${helpTip}`;
}

function windowHeader(tableId, key, metric, labelSuffix) {
  return sortableHeader(tableId, `${metric}_${key}`, `${windowLabels[key]}${labelSuffix}`);
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

function bindNameTooltips(scope) {
  scope.querySelectorAll(".name-cell[data-name-tooltip]").forEach(cell => {
    const text = cell.querySelector(".name-text");
    const isOverflowing = text ? text.scrollWidth > text.clientWidth + 1 : false;
    cell.classList.toggle("has-name-tooltip", isOverflowing);
  });
}

function metricCell(value, formatter = fmtYi) {
  return `<td class="num ${flowClass(value)}">${formatter(value)}</td>`;
}

function expandedRowScrollOffset(table) {
  const tableHeadHeight = table?.tHead?.getBoundingClientRect?.().height || 34;
  return pxVar("--capital-header-height", 60) + pxVar("--capital-section-nav-height", 62) + tableHeadHeight - 1;
}

function scrollExpandedRowIntoView(tableId, key) {
  const table = document.getElementById(tableId);
  if (!table) return;
  const row = [...table.querySelectorAll(".data-row")].find(item => item.dataset.rowKey === key);
  if (!row) return;
  const top = row.getBoundingClientRect().top + window.scrollY - expandedRowScrollOffset(table);
  window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
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
        <th class="num-head">${sortableHeader(tableId, "change_pct", "当日涨跌幅")}</th>
        <th class="num-head">${sortableHeader(tableId, "turnover_5d", "5日成交均值占比")}</th>
        ${windowKeys.map(key => `<th class="num-head">${windowHeader(tableId, key, "flow", "净申购")}</th>`).join("")}
        ${windowKeys.map(key => `<th class="num-head">${windowHeader(tableId, key, "ratio", "净申购占比")}</th>`).join("")}
        <th class="num-head">${sortableHeader(tableId, "scale_yi", "当日ETF规模")}</th>
      </tr>
    </thead>
    <tbody>
      ${displayRows.map(row => {
        const key = rowKey(row);
        const expanded = Boolean(expandedRows[tableId]?.[key]);
        const displayName = formatIndexName(row);
        return `
          <tr class="data-row${expanded ? " expanded" : ""}" data-row-key="${key}" tabindex="0">
            <td class="name-cell" data-name-tooltip="${escapeHtml(displayName)}">
              <span class="expand-mark">${expanded ? "−" : "+"}</span><span class="name-text">${displayName}</span>
            </td>
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
  bindNameTooltips(table);
}

function toggleRow(tableId, sectionKey, key) {
  expandedRows[tableId] = expandedRows[tableId] || {};
  const shouldExpand = !expandedRows[tableId][key];
  expandedRows[tableId][key] = shouldExpand;
  renderTable(tableId, sectionKey);
  if (shouldExpand) {
    window.requestAnimationFrame(() => scrollExpandedRowIntoView(tableId, key));
  }
}
