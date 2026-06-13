function renderTotalFlow(data) {
  const wrap = document.getElementById("totalFlowCards");
  const columns = [
    ["北上资金", key => hsgtValue(data, key, "北上资金")],
    ["南下资金", key => hsgtValue(data, key, "南下资金")],
    ["宽基被动ETF(>=20亿)", key => sectionValue(data, key, "broad")],
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
        <div class="window-cell" role="cell">5日成交均值占比</div>
        <div class="matrix-value muted" role="cell">--</div>
        <div class="matrix-value muted" role="cell">--</div>
        ${["broad", "a_industry", "hk_industry", "strategy"].map(sectionKey => {
          const value = sectionTurnoverRatio(data, "5d", sectionKey);
          return `<div class="matrix-value neutral" role="cell">${fmtPct(value)}</div>`;
        }).join("")}
      </div>
      ${windowKeys.map(key => `
        <div class="flow-matrix-row" role="row">
          <div class="window-cell" role="cell">${windowTradeLabels[key]}</div>
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
  const quality = data?.etf?.quality || {};
  if (!status) {
    el.textContent = "";
    el.className = "data-status";
    return;
  }
  const parts = [
    `ETF数据日 ${status.as_of_date || "--"}`,
    `价格日 ${status.price_date || "--"}`,
    `份额日 ${status.share_date || "--"}`,
    `净值日 ${status.nav_date || "未发布"}`,
    `净申购估值 ${quality.price_source_label || "--"}`
  ];
  if (status.status === "fallback") {
    parts.push("已回退到最近完整交易日");
  }
  if (status.payload_cache_status === "stale") {
    parts.push("使用上次成功缓存");
  }
  el.textContent = parts.join(" · ");
  el.className = `data-status${status.status === "fallback" ? " warning" : ""}`;
}

function renderAiSummary(data) {
  const panel = document.getElementById("aiSummaryPanel");
  const body = document.getElementById("aiSummaryBody");
  const source = document.getElementById("aiSummarySource");
  if (!body) return;
  const summary = data?.ai_summary || {};
  const focusItems = Array.isArray(summary.focus_items) ? summary.focus_items : [];
  const shouldShow = summary.source === "deepseek" && (summary.headline || focusItems.length);
  if (panel) {
    panel.hidden = !shouldShow;
  }
  if (!shouldShow) {
    body.innerHTML = "";
    if (source) source.textContent = "";
    return;
  }
  if (source) {
    source.textContent = summary.model || "";
  }
  body.innerHTML = `
    ${summary.headline ? `<div class="ai-summary-headline">${escapeHtml(summary.headline)}</div>` : ""}
    <div class="ai-summary-list">
      ${focusItems.map(item => `
        <div class="ai-summary-item">
          <div class="ai-summary-item-title">${escapeHtml(item.title || "")}</div>
          <div class="ai-summary-item-detail">${escapeHtml(item.detail || "")}</div>
        </div>
      `).join("")}
    </div>
  `;
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
    loadDeepSeekSummary(data);
  } catch (err) {
    console.error("资金流向加载失败", err);
    document.getElementById("totalFlowCards").innerHTML = `<div class="empty">资金流向加载失败：${err.message}</div>`;
  }
}

async function loadDeepSeekSummary(data) {
  const params = new URLSearchParams();
  if (data?.selected_window) {
    params.set("window", data.selected_window);
  }
  try {
    const response = await fetch(`/api/capital-flow/ai-summary?${params.toString()}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    if (payload?.ai_summary?.source === "deepseek") {
      latestCapitalFlowData = { ...latestCapitalFlowData, ai_summary: payload.ai_summary };
      renderAiSummary(latestCapitalFlowData);
    }
  } catch (err) {
    console.warn("DeepSeek摘要加载失败，隐藏AI总结", err);
  }
}

function renderCapitalFlow(data) {
  if (!data) return;
  renderDataStatus(data);
  renderAiSummary(data);
  renderTotalFlow(data);
  renderTable("broadTable", "broad");
  renderTable("aIndustryTable", "a_industry");
  renderTable("hkIndustryTable", "hk_industry");
  renderTable("strategyTable", "strategy");
}

loadCapitalFlow();
setupSectionNav();

loadCapitalFlow();
setupSectionNav();
