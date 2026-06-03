const state = {
  dates: [],
  selectedDate: null,
  latestDate: null,
  manifest: null,
  searchIndex: null,
  industryTrends: null,
  mode: "date",
  columns: [],
  rows: [],
};

const els = {
  subtitle: document.querySelector("#subtitle"),
  searchForm: document.querySelector("#searchForm"),
  searchInput: document.querySelector("#searchInput"),
  clearSearch: document.querySelector("#clearSearch"),
  dateTabs: document.querySelector("#dateTabs"),
  modeLabel: document.querySelector("#modeLabel"),
  summaryTitle: document.querySelector("#summaryTitle"),
  summaryMeta: document.querySelector("#summaryMeta"),
  tableHead: document.querySelector("#tableHead"),
  tableBody: document.querySelector("#tableBody"),
  mobileList: document.querySelector("#mobileList"),
  emptyState: document.querySelector("#emptyState"),
  industrySubtitle: document.querySelector("#industrySubtitle"),
  industryStat: document.querySelector("#industryStat"),
  industryChartMeta: document.querySelector("#industryChartMeta"),
  industryChart: document.querySelector("#industryChart"),
  industryLegend: document.querySelector("#industryLegend"),
  industryChangeMeta: document.querySelector("#industryChangeMeta"),
  newIndustryMeta: document.querySelector("#newIndustryMeta"),
  newIndustryList: document.querySelector("#newIndustryList"),
  removedIndustryMeta: document.querySelector("#removedIndustryMeta"),
  removedIndustryList: document.querySelector("#removedIndustryList"),
  industryTableBody: document.querySelector("#industryTableBody"),
  chartTooltip: document.querySelector("#chartTooltip"),
};

const primaryColumns = [
  "signal_date",
  "ts_code",
  "code",
  "stock_code",
  "证券代码",
  "股票代码",
  "name",
  "stock_name",
  "股票名称",
  "股票简称",
  "证券简称",
  "trade_date",
  "date",
  "industry",
  "close",
  "vol_ratio",
  "j",
  "ma60",
  "trend_short",
  "bull_bear",
  "last_signal",
  "days_since",
];

const hiddenColumns = new Set(["source_file"]);

const codeColumns = new Set([
  "ts_code",
  "code",
  "symbol",
  "stock_code",
  "seccode",
  "security_code",
  "ticker",
  "gupiaodaima",
  "zhengquandaima",
  "股票代码",
  "证券代码",
]);

const nameColumns = new Set([
  "name",
  "stock_name",
  "short_name",
  "security_name",
  "gupiaomingcheng",
  "zhengquanjiancheng",
  "zhengquanmingcheng",
  "股票名称",
  "股票简称",
  "证券简称",
  "证券名称",
]);

const chartColors = [
  "#0f8b8d",
  "#c44536",
  "#31572c",
  "#5f4bb6",
  "#d08900",
  "#2f6690",
  "#9b5b9b",
  "#d95f3b",
];

function getGradientId(idx) {
  return `grad-${idx}`;
}

function displayDate(raw) {
  if (!raw || raw.length !== 8) return raw || "--";
  return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
}

function formatValue(raw) {
  if (raw === undefined || raw === null) return "--";
  const n = Number(raw);
  if (Number.isNaN(n)) return String(raw);
  if (Number.isInteger(n)) return n.toLocaleString("zh-CN");
  return n.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function intValue(raw) {
  const n = Number(raw);
  return Number.isNaN(n) ? 0 : n;
}

function svgNode(tag, attrs = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs)) {
    node.setAttribute(key, value);
  }
  return node;
}

function displayDateShort(raw) {
  if (!raw || raw.length !== 8) return raw || "--";
  return `${raw.slice(4, 6)}/${raw.slice(6, 8)}`;
}

function formatChange(value) {
  if (value > 0) return `+${value}`;
  return String(value);
}

function changeClass(value) {
  if (value > 0) return "change-up";
  if (value < 0) return "change-down";
  return "change-flat";
}

function countMap(row) {
  return new Map((row.counts || []).map((item) => [item.date, Number(item.count || 0)]));
}

function getColorOpacity(color, opacity) {
  if (color.startsWith("#")) {
    const r = parseInt(color.slice(1, 3), 16);
    const g = parseInt(color.slice(3, 5), 16);
    const b = parseInt(color.slice(5, 7), 16);
    return `rgba(${r},${g},${b},${opacity})`;
  }
  return color;
}

function renderIndustryChart(payload) {
  const dates = payload.dates || [];
  const rows = (payload.latest || []).slice(0, 8);
  const svg = els.industryChart;
  svg.innerHTML = "";
  els.industryLegend.innerHTML = "";

  if (!dates.length || !rows.length) {
    const text = svgNode("text", {
      x: 360,
      y: 130,
      "text-anchor": "middle",
      class: "chart-label",
    });
    text.textContent = "暂无行业趋势数据";
    svg.append(text);
    return;
  }

  const width = 720;
  const height = 260;
  const pad = { left: 44, right: 18, top: 18, bottom: 36 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const maxCount = Math.max(
    1,
    ...rows.flatMap((row) => (row.counts || []).map((item) => Number(item.count || 0))),
  );
  const yMax = Math.max(5, Math.ceil(maxCount / 5) * 5);

  const xFor = (idx) => pad.left + (dates.length === 1 ? plotW / 2 : (plotW * idx) / (dates.length - 1));
  const yFor = (count) => pad.top + plotH - (Number(count || 0) / yMax) * plotH;

  // --- Defs for gradients ---
  const defs = svgNode("defs");
  rows.forEach((row, rowIdx) => {
    const color = chartColors[rowIdx % chartColors.length];
    const id = getGradientId(rowIdx);
    const g = svgNode("linearGradient", { id, x1: "0", y1: "0", x2: "0", y2: "1" });
    const stop1 = svgNode("stop", { offset: "0%", "stop-color": color, "stop-opacity": "0.20" });
    const stop2 = svgNode("stop", { offset: "100%", "stop-color": color, "stop-opacity": "0.02" });
    g.append(stop1, stop2);
    defs.append(g);
  });
  svg.append(defs);

  // --- Y-axis grid lines and labels ---
  for (let i = 0; i <= 4; i += 1) {
    const value = Math.round((yMax * i) / 4);
    const y = yFor(value);
    svg.append(
      svgNode("line", {
        x1: pad.left,
        y1: y,
        x2: width - pad.right,
        y2: y,
        class: "chart-grid-line",
      }),
    );
    const label = svgNode("text", { x: pad.left - 8, y: y + 4, "text-anchor": "end", class: "chart-label" });
    label.textContent = value;
    svg.append(label);
  }

  // --- X-axis labels ---
  const labelStep = Math.max(1, Math.ceil(dates.length / 6));
  dates.forEach((date, idx) => {
    if (idx % labelStep !== 0 && idx !== dates.length - 1) return;
    const label = svgNode("text", {
      x: xFor(idx),
      y: height - 4,
      "text-anchor": "middle",
      class: "chart-label",
    });
    label.textContent = displayDateShort(date);
    svg.append(label);
  });

  // --- Axes ---
  svg.append(
    svgNode("line", {
      x1: pad.left,
      y1: pad.top,
      x2: pad.left,
      y2: height - pad.bottom,
      class: "chart-axis",
    }),
  );
  svg.append(
    svgNode("line", {
      x1: pad.left,
      y1: height - pad.bottom,
      x2: width - pad.right,
      y2: height - pad.bottom,
      class: "chart-axis",
    }),
  );

  // --- Tooltip overlay ---
  const tooltipOverlay = svgNode("rect", {
    x: pad.left,
    y: pad.top,
    width: plotW,
    height: plotH,
    fill: "transparent",
    class: "chart-tooltip-overlay",
  });
  tooltipOverlay.setAttribute("style", "cursor: crosshair;");
  svg.append(tooltipOverlay);

  // Tooltip line
  const tooltipLine = svgNode("line", {
    x1: 0,
    y1: pad.top,
    x2: 0,
    y2: height - pad.bottom,
    class: "chart-tooltip-line",
    style: "display: none;",
  });
  svg.append(tooltipLine);

  // Tooltip dot group
  const tooltipDots = svgNode("g", { class: "chart-tooltip-dots", style: "display: none;" });
  svg.append(tooltipDots);

  // Tooltip label
  const tooltipDateLabel = svgNode("text", {
    class: "chart-tooltip-date",
    "text-anchor": "middle",
    style: "display: none;",
  });
  svg.append(tooltipDateLabel);

  // --- Plot lines and area fills ---
  const lineGroups = [];
  const allPoints = [];

  rows.forEach((row, rowIdx) => {
    const color = chartColors[rowIdx % chartColors.length];
    const counts = countMap(row);
    const points = dates.map((date, idx) => [xFor(idx), yFor(counts.get(date) || 0)]);

    allPoints.push({ row, points, color, rowIdx });

    // Gradient area fill
    const areaPath =
      points
        .map(([x, y], idx) => `${idx === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`)
        .join(" ") +
      ` L${points[points.length - 1][0].toFixed(1)},${pad.top + plotH}` +
      ` L${points[0][0].toFixed(1)},${pad.top + plotH} Z`;

    svg.append(
      svgNode("path", {
        d: areaPath,
        fill: `url(#${getGradientId(rowIdx)})`,
        class: "chart-area",
      }),
    );

    // Line
    const linePath = points
      .map(([x, y], idx) => `${idx === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`)
      .join(" ");
    const line = svgNode("path", { d: linePath, stroke: color, class: "chart-line" });
    svg.append(line);
    lineGroups.push({ line, points, color, row, rowIdx });

    // Data point dots
    points.forEach(([x, y]) => {
      svg.append(svgNode("circle", { cx: x, cy: y, r: 2.5, fill: color, class: "chart-dot" }));
    });

    // Last point highlight
    const lastPoint = points[points.length - 1];
    svg.append(
      svgNode("circle", {
        cx: lastPoint[0],
        cy: lastPoint[1],
        r: 5,
        fill: color,
        class: "chart-point",
      }),
    );
    svg.append(
      svgNode("circle", {
        cx: lastPoint[0],
        cy: lastPoint[1],
        r: 3,
        fill: "#fff",
        class: "chart-point-inner",
      }),
    );

    // Legend
    const legend = document.createElement("div");
    legend.className = "legend-item";
    legend.dataset.idx = rowIdx;
    const swatch = document.createElement("span");
    swatch.className = "legend-swatch";
    swatch.style.background = color;
    const name = document.createElement("span");
    name.className = "legend-name";
    name.textContent = `${row.industry} ${row.latest_count}`;
    legend.append(swatch, name);
    els.industryLegend.append(legend);

    // Legend hover effect
    legend.addEventListener("mouseenter", () => {
      line.setAttribute("style", `stroke: ${color}; stroke-width: 4; opacity: 1;`);
      document.querySelectorAll(".chart-line").forEach((l) => {
        if (l !== line) {
          l.setAttribute("style", "opacity: 0.2;");
        }
      });
      document.querySelectorAll(".chart-dot, .chart-point, .chart-point-inner").forEach((d) => {
        d.setAttribute("style", "opacity: 0.15;");
      });
      document.querySelectorAll(`.chart-point[fill="${color}"], .chart-dot[fill="${color}"]`).forEach((d) => {
        d.setAttribute("style", "opacity: 1;");
      });
    });
    legend.addEventListener("mouseleave", () => {
      document
        .querySelectorAll(".chart-line, .chart-dot, .chart-point, .chart-point-inner")
        .forEach((el) => el.removeAttribute("style"));
    });
  });

  // --- Mouse tracking for tooltip ---
  tooltipOverlay.addEventListener("mousemove", (e) => {
    const rect = svg.getBoundingClientRect();
    const scaleX = width / rect.width;
    const mx = (e.clientX - rect.left) * scaleX;

    if (mx < pad.left || mx > width - pad.right) {
      tooltipLine.setAttribute("style", "display: none;");
      tooltipDots.setAttribute("style", "display: none;");
      tooltipDateLabel.setAttribute("style", "display: none;");
      return;
    }

    // Find closest date index
    let closestIdx = 0;
    let minDist = Infinity;
    dates.forEach((_, idx) => {
      const dist = Math.abs(mx - xFor(idx));
      if (dist < minDist) {
        minDist = dist;
        closestIdx = idx;
      }
    });

    const tx = xFor(closestIdx);
    tooltipLine.setAttribute("x1", tx.toFixed(1));
    tooltipLine.setAttribute("x2", tx.toFixed(1));
    tooltipLine.setAttribute("style", "display: block;");

    // Date label at top
    tooltipDateLabel.setAttribute("x", tx.toFixed(1));
    tooltipDateLabel.setAttribute("y", (pad.top - 6).toFixed(1));
    tooltipDateLabel.textContent = displayDateShort(dates[closestIdx]);
    tooltipDateLabel.setAttribute("style", "display: block;");

    // Dots for each line
    tooltipDots.innerHTML = "";
    lineGroups.forEach(({ points, color, row, rowIdx: idx }) => {
      const [x, y] = points[closestIdx];
      const dot = svgNode("circle", {
        cx: x.toFixed(1),
        cy: y.toFixed(1),
        r: 5,
        fill: color,
        class: "chart-tooltip-dot",
      });
      dot.setAttribute("style", "stroke: #fff; stroke-width: 1.5;");
      tooltipDots.append(dot);
    });
    tooltipDots.setAttribute("style", "display: block;");
  });

  tooltipOverlay.addEventListener("mouseleave", () => {
    tooltipLine.setAttribute("style", "display: none;");
    tooltipDots.setAttribute("style", "display: none;");
    tooltipDateLabel.setAttribute("style", "display: none;");
  });
}

function renderNewIndustries(payload) {
  const rows = payload.new_latest || [];
  els.newIndustryList.innerHTML = "";
  els.newIndustryMeta.textContent = `${rows.length} 个`;

  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "new-industry-empty";
    empty.textContent = "最新日期没有新进板块";
    els.newIndustryList.append(empty);
    return;
  }

  for (const row of rows.slice(0, 12)) {
    const item = document.createElement("div");
    item.className = "new-industry-item";
    const name = document.createElement("strong");
    name.textContent = row.industry;
    const count = document.createElement("span");
    count.textContent = `${row.latest_count} 只`;
    item.append(name, count);
    els.newIndustryList.append(item);
  }
}

function renderRemovedIndustries(payload) {
  const rows = payload.removed_latest || [];
  els.removedIndustryList.innerHTML = "";
  els.removedIndustryMeta.textContent = `${rows.length} 个`;

  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "new-industry-empty";
    empty.textContent = "最新日期没有消失板块";
    els.removedIndustryList.append(empty);
    return;
  }

  for (const row of rows.slice(0, 12)) {
    const item = document.createElement("div");
    item.className = "new-industry-item removed-industry-item";
    const name = document.createElement("strong");
    name.textContent = row.industry;
    const count = document.createElement("span");
    count.textContent = `前日 ${row.previous_count} 只`;
    item.append(name, count);
    els.removedIndustryList.append(item);
  }
}

function renderIndustryTable(payload) {
  els.industryTableBody.innerHTML = "";
  const rows = (payload.latest || []).slice(0, 18);

  for (const row of rows) {
    const tr = document.createElement("tr");

    const industry = document.createElement("td");
    industry.textContent = row.industry;
    industry.title = row.industry;

    const latest = document.createElement("td");
    latest.textContent = row.latest_count;

    const change = document.createElement("td");
    change.className = changeClass(row.change);
    change.textContent = formatChange(row.change);

    const firstSeen = document.createElement("td");
    firstSeen.textContent = displayDate(row.first_seen_date);

    tr.append(industry, latest, change, firstSeen);
    els.industryTableBody.append(tr);
  }
}

function renderIndustryPanel(payload) {
  const latestRows = payload.latest || [];
  const totalIndustries = latestRows.length;
  const totalStocks = latestRows.reduce((sum, row) => sum + Number(row.latest_count || 0), 0);
  const newCount = (payload.new_latest || []).length;
  const removedCount = (payload.removed_latest || []).length;

  els.industrySubtitle.textContent = `${displayDate(payload.latest_date)} 行业分布`;
  els.industryStat.textContent = `${totalIndustries} 个行业 · ${totalStocks} 只股票`;
  els.industryChartMeta.textContent = `最新 Top 8 · ${payload.dates?.length || 0} 天`;
  els.industryChangeMeta.textContent = payload.previous_date
    ? `${displayDate(payload.previous_date)} → ${displayDate(payload.latest_date)}`
    : displayDate(payload.latest_date);

  renderIndustryChart(payload);
  renderNewIndustries(payload);
  renderRemovedIndustries(payload);
  renderIndustryTable(payload);

  if (newCount > 0 || removedCount > 0) {
    els.industrySubtitle.textContent = `${displayDate(payload.latest_date)} 新进 ${newCount} 个 · 消失 ${removedCount} 个`;
  }
}

async function loadIndustryTrends() {
  try {
    const res = await fetch("data/industry_trends.json");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const payload = await res.json();
    state.industryTrends = payload;
    renderIndustryPanel(payload);
  } catch (err) {
    els.industrySubtitle.textContent = "行业数据读取失败";
    els.industryStat.textContent = err.message;
    els.industryChartMeta.textContent = "--";
    els.industryChangeMeta.textContent = "--";
    els.industryChart.innerHTML = "";
    els.industryLegend.innerHTML = "";
    els.newIndustryList.innerHTML = "";
    els.removedIndustryList.innerHTML = "";
    els.industryTableBody.innerHTML = "";
  }
}

async function loadManifest() {
  const res = await fetch("data/manifest.json");
  const data = await res.json();
  state.manifest = data;

  const dates = Object.keys(data).filter((k) => k.length === 8).sort();
  state.dates = dates;
  state.latestDate = dates[dates.length - 1];

  renderDateTabs();
  loadIndustryTrends();
  selectDate(state.latestDate);
}

function renderDateTabs() {
  els.dateTabs.innerHTML = "";
  for (const date of state.dates) {
    const btn = document.createElement("button");
    btn.textContent = displayDate(date);
    btn.dataset.date = date;
    if (date === state.selectedDate) btn.classList.add("active");
    btn.addEventListener("click", () => selectDate(date));
    els.dateTabs.append(btn);
  }
}

function displayDate(raw) {
  if (!raw || raw.length !== 8) return raw || "--";
  return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
}

async function selectDate(date) {
  state.selectedDate = date;
  document.querySelectorAll(".date-tabs button").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.date === date);
  });

  const meta = state.manifest[date];
  const label = meta?.label || "日期";
  els.modeLabel.textContent = label;
  els.summaryTitle.textContent = displayDate(date);

  const columns = meta?.columns || [];
  state.columns = columns;

  if (meta?.stock_data) {
    try {
      const res = await fetch(meta.stock_data);
      const data = await res.json();
      state.rows = data;
      renderTable();
      els.summaryMeta.textContent = `${data.length} 只`;
    } catch {
      state.rows = [];
      renderTable();
      els.summaryMeta.textContent = "加载失败";
    }
  } else {
    state.rows = [];
    renderTable();
    els.summaryMeta.textContent = meta?.note || "";
  }
}

function displayValue(val, col) {
  if (val === undefined || val === null) return "--";
  if (codeColumns.has(col)) return String(val);
  if (nameColumns.has(col)) return String(val);
  const n = Number(val);
  if (Number.isNaN(n)) return String(val);
  if (Number.isInteger(n)) return n.toLocaleString("zh-CN");
  return n.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function sortKey(val, col) {
  if (val === undefined || val === null) return -Infinity;
  const n = Number(val);
  if (!Number.isNaN(n)) return n;
  return String(val);
}

function colLabel(col) {
  const labels = {
    signal_date: "信号日期",
    ts_code: "TS代码",
    trade_date: "交易日期",
    name: "名称",
    stock_name: "名称",
    close: "收盘价",
    vol_ratio: "量比",
    j: "KDJ_J",
    ma60: "MA60",
    trend_short: "知行短趋",
    bull_bear: "多空",
    last_signal: "末次信号",
    days_since: "距今",
  };
  return labels[col] || col;
}

function renderTable() {
  const rows = state.rows;
  els.tableHead.innerHTML = "";
  els.tableBody.innerHTML = "";
  els.mobileList.innerHTML = "";

  if (!rows.length) {
    els.emptyState.hidden = false;
    return;
  }
  els.emptyState.hidden = true;

  const cols = pickColumns(rows);
  const sortCol = state.columns.find((c) => c.sort)?.key;
  const sortDesc = state.columns.find((c) => c.sort)?.desc ?? true;

  if (sortCol) {
    rows.sort((a, b) => {
      const va = sortKey(a[sortCol], sortCol);
      const vb = sortKey(b[sortCol], sortCol);
      if (typeof va === "number" && typeof vb === "number") {
        return sortDesc ? vb - va : va - vb;
      }
      return sortDesc
        ? String(vb).localeCompare(String(va))
        : String(va).localeCompare(String(vb));
    });
  }

  // Table header
  const thead = document.createElement("tr");
  for (const col of cols) {
    const th = document.createElement("th");
    th.textContent = colLabel(col);
    thead.append(th);
  }
  els.tableHead.append(thead);

  // Table body
  for (const row of rows) {
    const tr = document.createElement("tr");
    for (const col of cols) {
      const td = document.createElement("td");
      td.setAttribute("data-col", col);
      const val = row[col];
      td.textContent = displayValue(val, col);
      if (col === "change" || col === "pct_chg" || col === "涨幅") {
        const n = Number(val);
        td.className = n > 0 ? "change-up" : n < 0 ? "change-down" : "change-flat";
      }
      tr.append(td);
    }
    els.tableBody.append(tr);
  }

  // Mobile cards
  const primary = cols.slice(0, 4);
  const rest = cols.slice(4);

  for (const row of rows) {
    const card = document.createElement("div");
    card.className = "stock-card";

    const header = document.createElement("header");
    for (const col of primary) {
      const val = row[col];
      if (codeColumns.has(col)) {
        const code = document.createElement("span");
        code.className = "stock-code";
        code.textContent = String(val);
        header.append(code);
      } else if (nameColumns.has(col)) {
        const name = document.createElement("strong");
        name.className = "stock-name";
        name.textContent = String(val);
        header.append(name);
      } else if (col === "industry") {
        const tag = document.createElement("span");
        tag.className = "stock-industry";
        tag.textContent = String(val || "");
        header.append(tag);
      } else {
        const span = document.createElement("span");
        span.textContent = displayValue(val, col);
        header.append(span);
      }
    }
    card.append(header);

    const grid = document.createElement("div");
    grid.className = "card-grid";

    for (const col of rest) {
      const metric = document.createElement("div");
      metric.className = "metric";
      const label = document.createElement("span");
      label.textContent = colLabel(col);
      const val = document.createElement("strong");
      val.textContent = displayValue(row[col], col);
      if (col === "change" || col === "pct_chg") {
        const n = Number(row[col]);
        val.className = n > 0 ? "change-up" : n < 0 ? "change-down" : "";
      }
      metric.append(label, val);
      grid.append(metric);
    }
    card.append(grid);
    els.mobileList.append(card);
  }
}

function pickColumns(rows) {
  if (state.columns.length > 0) {
    const keys = state.columns.map((c) => c.key);
    return keys;
  }

  if (rows.length === 0) return [];
  const sample = rows[0];
  const keys = Object.keys(sample).filter((k) => !hiddenColumns.has(k));

  const ranked = keys.sort((a, b) => {
    const ai = primaryColumns.indexOf(a);
    const bi = primaryColumns.indexOf(b);
    if (ai !== -1 && bi !== -1) return ai - bi;
    if (ai !== -1) return -1;
    if (bi !== -1) return 1;
    return a.localeCompare(b);
  });

  return ranked;
}

// --- Search ---
els.searchForm.addEventListener("submit", (e) => {
  e.preventDefault();
  applySearch(els.searchInput.value.trim());
});

els.clearSearch.addEventListener("click", () => {
  els.searchInput.value = "";
  applySearch("");
});

els.searchInput.addEventListener("input", () => {
  if (els.searchInput.value === "") applySearch("");
});

function applySearch(query) {
  const rows = state.rows;
  const lower = query.toLowerCase();

  for (const tr of els.tableBody.querySelectorAll("tr")) {
    const match =
      !query ||
      Array.from(tr.cells).some((td) => td.textContent.toLowerCase().includes(lower));
    tr.style.display = match ? "" : "none";
  }

  for (const card of els.mobileList.querySelectorAll(".stock-card")) {
    const match = !query || card.textContent.toLowerCase().includes(lower);
    card.style.display = match ? "" : "none";
  }

  if (query) {
    const visible =
      els.tableBody.querySelectorAll('tr[style*="display: none"]').length;
    const total = rows.length;
    els.summaryMeta.textContent = rows.length
      ? `${total - visible} / ${total}`
      : "-";
  } else {
    const meta = state.manifest[state.selectedDate];
    els.summaryMeta.textContent = meta?.note || (rows.length ? `${rows.length} 只` : "");
  }
}

loadManifest();
