function flowClass(value) {
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "neutral";
}

function yiFractionDigits(value) {
  const absValue = Math.abs(Number(value || 0));
  if (absValue >= 100) return 0;
  if (absValue >= 10) return 1;
  return 2;
}

function fmtYi(value) {
  const digits = yiFractionDigits(value);
  return `${yiFmtByDigits[digits].format(Number(value || 0))} 亿`;
}

function fmtPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return `${pctFmt.format(Number(value))}%`;
}

function formatIndexName(row) {
  const name = row.display_name || row.index_name;
  return row.index_code ? `${name}（${row.index_code}）` : name;
}

function sumBy(rows, key) {
  return (rows || []).reduce((total, row) => total + Number(row?.[key] || 0), 0);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
