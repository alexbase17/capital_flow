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
    const ratios = windowPoints
      .filter(item => Number(item.start_scale_yi || 0) > 0)
      .map(item => Number(item.value || 0) / Number(item.start_scale_yi || 0) * 100);
    return {
      date: point.date,
      start_date: windowPoints[0]?.date || "",
      end_date: point.date,
      value: ratios.length ? ratios.reduce((total, value) => total + value, 0) / ratios.length : null
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
  const height = 126;
  const plotTop = 8;
  const plotHeight = 104;
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
  const height = 126;
  const plotTop = 8;
  const plotHeight = 104;
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

function renderLineChart(points, label, valueLabel, formatter = fmtYi, options = {}) {
  if (!points.length) return '<div class="empty">暂无走势数据</div>';
  const width = 1040;
  const height = 126;
  const plotTop = 8;
  const plotHeight = 104;
  const { min, span } = chartDomain(points);
  const zeroY = plotTop + plotHeight - ((0 - min) / span) * plotHeight;
  const titleStyle = options.alignTitleCenter ? "" : ` style="--zero-y: ${zeroY.toFixed(1)}px"`;
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
      <div class="chart-title${options.alignTitleCenter ? " center" : ""}"${titleStyle}>${label}</div>
      <div class="flow-chart-body">
        <div class="flow-chart-plot" data-chart-tooltips='${tooltipPayload(JSON.stringify(tooltipValues))}'>
          <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(label)}">
            ${options.hideZeroLine ? "" : `<line x1="0" y1="${zeroY.toFixed(1)}" x2="${width}" y2="${zeroY.toFixed(1)}" class="zero-line"></line>`}
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
  if (!rollingPoints.length) return '<div class="empty">暂无5日滑动成交均值占比数据</div>';
  return renderLineChart(rollingPoints, label, "成交均值占比", fmtPct, { hideZeroLine: true, alignTitleCenter: true });
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
        ${renderRollingTurnoverRatioLine(turnoverPoints, "5日滑动窗口成交均值占比")}
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
      tooltip.classList.add("visible");
      const margin = 8;
      const tooltipWidth = Math.min(tooltip.offsetWidth, rect.width - margin * 2);
      const leftPx = Math.min(
        rect.width - tooltipWidth / 2 - margin,
        Math.max(tooltipWidth / 2 + margin, x * rect.width)
      );
      tooltip.style.left = `${leftPx}px`;
    });
    plot.addEventListener("pointerleave", () => {
      tooltip.classList.remove("visible");
    });
  });
}
