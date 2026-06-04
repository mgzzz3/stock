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
  detailPanel: document.querySelector("#detailPanel"),
  listPanel: document.querySelector("#listPanel"),
  detailBack: document.querySelector("#detailBack"),
  detailName: document.querySelector("#detailName"),
  detailCode: document.querySelector("#detailCode"),
  detailMeta: document.querySelector("#detailMeta"),
  klineChart: document.querySelector("#klineChart"),
  detailLoading: document.querySelector("#detailLoading"),
  detailError: document.querySelector("#detailError"),
  industryPanel: document.querySelector(".industry-panel"),
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
  "#8f2d56",
  "#5c677d",
];

const labelMap = {
  source_file: "来源",
  signal_date: "日期",
  ts_code: "代码",
  code: "代码",
  stock_code: "代码",
  name: "名称",
  stock_name: "名称",
  trade_date: "日期",
  date: "日期",
  industry: "行业",
  close: "收盘",
  vol_ratio: "量比",
  j: "KDJ J",
  ma60: "MA60",
  trend_short: "知行短趋",
  bull_bear: "知行多空",
  last_signal: "上次信号",
  days_since: "间隔",
  gp_signal: "GP信号",
  gp_var2z: "GP var2z",
  gp_last_signal: "GP上次",
  gp_days_since: "GP间隔",
};

function labelOf(column) {
  return labelMap[column] || column;
}

function displayDate(date) {
  if (!date || date.length !== 8) return date || "--";
  return `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)}`;
}

async function fetchJson(url) {
  const response = await fetch(url);
  let data;
  try {
    data = await response.json();
  } catch (error) {
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    throw error;
  }
  if (!response.ok) {
    throw new Error(data.error || `Request failed: ${response.status}`);
  }
  return data;
}

function setLoading(text) {
  els.summaryTitle.textContent = text;
  els.summaryMeta.textContent = "加载中";
  els.tableHead.innerHTML = "";
  els.tableBody.innerHTML = "";
  els.mobileList.innerHTML = "";
  els.emptyState.hidden = true;
}

function setError(error) {
  els.summaryTitle.textContent = "读取失败";
  els.summaryMeta.textContent = error.message || String(error);
  els.tableHead.innerHTML = "";
  els.tableBody.innerHTML = "";
  els.mobileList.innerHTML = "";
  els.emptyState.hidden = false;
  els.emptyState.textContent = error.message || "读取失败";
}

function isEmptyData(payload) {
  return !payload || !payload.columns || !Array.isArray(payload.columns) || payload.columns.length === 0;
}

function syncDates(payload) {
  state.dates = payload.dates || state.dates;
  state.latestDate = payload.latest_date || state.latestDate;
  state.selectedDate = payload.date || state.selectedDate || state.latestDate;
  renderDateTabs();
}

function renderDateTabs() {
  els.dateTabs.innerHTML = "";

  if (!state.dates.length) {
    const empty = document.createElement("span");
    empty.className = "summary-meta";
    empty.textContent = "暂无日期";
    els.dateTabs.append(empty);
    return;
  }

  for (const item of state.dates) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = displayDate(item.date);
    button.className = item.date === state.selectedDate && state.mode === "date" ? "active" : "";
    button.title = (item.files || []).join("\n");
    button.addEventListener("click", () => loadDate(item.date));
    els.dateTabs.append(button);
  }
}

function orderedColumns(columns) {
  const visibleColumns = columns.filter((column) => !hiddenColumns.has(column));
  const preferred = primaryColumns.filter((column) => visibleColumns.includes(column));
  const rest = visibleColumns.filter((column) => !preferred.includes(column));
  return [...preferred, ...rest];
}

function normalizedColumn(name) {
  return String(name).trim().toLowerCase().replace(/[\s_.-]+/g, "");
}

function columnInSet(column, set) {
  const raw = String(column).trim();
  const normalized = normalizedColumn(raw);
  for (const value of set) {
    if (raw === value || normalized === normalizedColumn(value)) {
      return true;
    }
  }
  return false;
}

function isCodeColumn(column) {
  return columnInSet(column, codeColumns);
}

function isNameColumn(column) {
  return columnInSet(column, nameColumns);
}

function isCodeLike(query) {
  return /^\d{6}(\.(SH|SZ|BJ))?$/i.test(query.trim());
}

function codeVariants(query) {
  const value = query.trim().toUpperCase();
  const variants = new Set([value]);
  if (value.includes(".")) {
    variants.add(value.split(".")[0]);
  } else if (/^\d{6}$/.test(value)) {
    variants.add(`${value}.SH`);
    variants.add(`${value}.SZ`);
    variants.add(`${value}.BJ`);
  }
  return variants;
}

function rowMatches(row, query, columns) {
  const codeCols = columns.filter(isCodeColumn);
  const nameCols = columns.filter(isNameColumn);
  const targetCols = [...new Set([...codeCols, ...nameCols])];
  const columnsToSearch = targetCols.length ? targetCols : columns;
  const codeQuery = isCodeLike(query);
  const variants = codeVariants(query);
  const loweredQuery = query.toLowerCase();

  return columnsToSearch.some((column) => {
    const value = String(row[column] ?? "").trim();
    if (!value) return false;

    if (codeCols.includes(column) && codeQuery) {
      const upperValue = value.toUpperCase();
      const bareValue = upperValue.split(".")[0];
      return variants.has(upperValue) || variants.has(bareValue);
    }

    return value.toLowerCase().includes(loweredQuery);
  });
}

function setIndustryError(message) {
  els.industrySubtitle.textContent = "行业数据读取失败";
  els.industryStat.textContent = message;
  els.industryChartMeta.textContent = "--";
  els.industryChangeMeta.textContent = "--";
  els.newIndustryMeta.textContent = "--";
  els.removedIndustryMeta.textContent = "--";
  els.industryChart.innerHTML = "";
  els.industryLegend.innerHTML = "";
  els.newIndustryList.innerHTML = "";
  els.removedIndustryList.innerHTML = "";
  els.industryTableBody.innerHTML = "";
}

function svgNode(tag, attrs = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs)) {
    node.setAttribute(key, value);
  }
  return node;
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
  const pad = { left: 42, right: 18, top: 18, bottom: 36 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const maxCount = Math.max(
    1,
    ...rows.flatMap((row) => (row.counts || []).map((item) => Number(item.count || 0))),
  );
  const yMax = Math.max(5, Math.ceil(maxCount / 5) * 5);
  const xFor = (idx) => pad.left + (dates.length === 1 ? plotW / 2 : (plotW * idx) / (dates.length - 1));
  const yFor = (count) => pad.top + plotH - (Number(count || 0) / yMax) * plotH;

  for (let i = 0; i <= 4; i += 1) {
    const value = Math.round((yMax * i) / 4);
    const y = yFor(value);
    svg.append(svgNode("line", { x1: pad.left, y1: y, x2: width - pad.right, y2: y, class: "chart-grid-line" }));
    const label = svgNode("text", { x: pad.left - 8, y: y + 4, "text-anchor": "end", class: "chart-label" });
    label.textContent = value;
    svg.append(label);
  }

  const labelStep = Math.max(1, Math.ceil(dates.length / 6));
  dates.forEach((date, idx) => {
    if (idx % labelStep !== 0 && idx !== dates.length - 1) return;
    const label = svgNode("text", { x: xFor(idx), y: height - 10, "text-anchor": "middle", class: "chart-label" });
    label.textContent = displayDate(date).slice(5);
    svg.append(label);
  });

  svg.append(svgNode("line", { x1: pad.left, y1: pad.top, x2: pad.left, y2: height - pad.bottom, class: "chart-axis" }));
  svg.append(svgNode("line", { x1: pad.left, y1: height - pad.bottom, x2: width - pad.right, y2: height - pad.bottom, class: "chart-axis" }));

  rows.forEach((row, rowIdx) => {
    const color = chartColors[rowIdx % chartColors.length];
    const counts = countMap(row);
    const points = dates.map((date, idx) => [xFor(idx), yFor(counts.get(date) || 0)]);
    const path = points.map(([x, y], idx) => `${idx === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    svg.append(svgNode("path", { d: path, stroke: color, class: "chart-line" }));

    const lastPoint = points[points.length - 1];
    svg.append(svgNode("circle", { cx: lastPoint[0], cy: lastPoint[1], r: 4, fill: color, class: "chart-point" }));

    const legend = document.createElement("div");
    legend.className = "legend-item";
    const swatch = document.createElement("span");
    swatch.className = "legend-swatch";
    swatch.style.background = color;
    const name = document.createElement("span");
    name.className = "legend-name";
    name.textContent = `${row.industry} ${row.latest_count}`;
    legend.append(swatch, name);
    els.industryLegend.append(legend);
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
    const path = state.manifest?.industry_trends || "data/industry_trends.json";
    state.industryTrends = await fetchJson(path);
    renderIndustryPanel(state.industryTrends);
  } catch (error) {
    setIndustryError(error.message || String(error));
  }
}

/* ── Stock Detail / K-line ── */

function getTsCode(row, columns) {
  const codeCol = columns.find((c) => isCodeColumn(c));
  if (!codeCol) return "";
  const raw = String(row[codeCol] ?? "").trim();
  // Normalize to ts_code format (e.g. 000001.SZ, 600000.SH)
  if (raw.includes(".")) return raw.toUpperCase();
  if (/^\d{6}$/.test(raw)) return raw; // fallback, server will try DB lookup
  return raw;
}

function klineLookupKeys(tsCode) {
  const value = String(tsCode || "").trim().toUpperCase();
  if (!value) return [];
  const keys = [value];
  if (value.includes(".")) {
    keys.push(value.split(".")[0]);
  }
  return [...new Set(keys)];
}

function staticKlinePath(tsCode) {
  const index = state.manifest?.kline_index || {};
  for (const key of klineLookupKeys(tsCode)) {
    if (index[key]) {
      return index[key];
    }
  }
  return "";
}

async function loadStockDetailData(tsCode) {
  const staticPath = staticKlinePath(tsCode);
  if (staticPath) {
    try {
      return await fetchJson(staticPath);
    } catch (error) {
      // Fall back to the local preview API below when static detail data is stale or missing.
    }
  }

  return fetchJson(`/api/kline?ts_code=${encodeURIComponent(tsCode)}&limit=120`);
}

function showListView() {
  els.detailPanel.hidden = true;
  els.listPanel.hidden = false;
  els.industryPanel.hidden = false;
}

function showStockDetail(tsCode, name) {
  els.listPanel.hidden = true;
  els.industryPanel.hidden = true;
  els.detailPanel.hidden = false;
  els.detailName.textContent = name || "--";
  els.detailCode.textContent = tsCode;
  els.detailLoading.hidden = false;
  els.detailError.hidden = true;
  els.klineChart.innerHTML = "";
  els.detailMeta.textContent = "获取数据中…";

  loadStockDetailData(tsCode)
    .then((data) => {
      els.detailLoading.hidden = true;
      if (data.error) {
        els.detailError.hidden = false;
        els.detailError.textContent = data.error;
        return;
      }
      els.detailName.textContent = data.name || name || "--";
      els.detailMeta.textContent = `${data.count} 个交易日`;
      renderKlineChart(data.kline, data.name || tsCode);
    })
    .catch((err) => {
      els.detailLoading.hidden = true;
      els.detailError.hidden = false;
      els.detailError.textContent = `请求失败: ${err.message}。请重新运行 export_web_data.py 导出详情数据；本地预览也可以使用 h5_server.py 启动服务。`;
    });
}

function backToList() {
  showListView();
}

els.detailBack.addEventListener("click", backToList);

/* ── Candlestick Chart (SVG) ── */

function renderKlineChart(kline, stockLabel) {
  const svg = els.klineChart;
  svg.innerHTML = "";

  if (!kline || kline.length < 2) {
    const t = svgNode("text", { x: 400, y: 200, "text-anchor": "middle", class: "kline-label" });
    t.textContent = "K线数据不足";
    svg.append(t);
    return;
  }

  const width = 800;
  const height = 400;
  const pad = { left: 48, right: 16, top: 28, bottom: 28 };
  const volHeight = 50;
  const mainHeight = height - pad.top - pad.bottom - volHeight - 8;
  const plotW = width - pad.left - pad.right;

  const opens = kline.map((d) => Number(d.open));
  const highs = kline.map((d) => Number(d.high));
  const lows = kline.map((d) => Number(d.low));
  const closes = kline.map((d) => Number(d.close));
  const volumes = kline.map((d) => Number(d.vol || 0));
  const dates = kline.map((d) => d.trade_date || "");

  // Price range
  let minPrice = Math.min(...lows);
  let maxPrice = Math.max(...highs);
  const padPrice = (maxPrice - minPrice) * 0.08 || 0.5;
  minPrice -= padPrice;
  maxPrice += padPrice;

  // Volume range
  const maxVol = Math.max(...volumes, 1);

  const xFor = (i) => pad.left + (plotW * i) / (kline.length - 1);
  const yFor = (p) => pad.top + mainHeight - ((p - minPrice) / (maxPrice - minPrice)) * mainHeight;
  const volYFor = (v) => pad.top + mainHeight + 8 + volHeight - (v / maxVol) * volHeight;

  const candleWidth = Math.max(2, Math.min(10, plotW / kline.length * 0.6));
  const halfCandle = candleWidth / 2;

  // Grid lines
  const gridCount = 5;
  for (let i = 0; i <= gridCount; i++) {
    const y = pad.top + (mainHeight * i) / gridCount;
    svg.append(svgNode("line", { x1: pad.left, y1: y, x2: width - pad.right, y2: y, class: "kline-grid" }));
    const label = svgNode("text", { x: pad.left - 6, y: y + 4, "text-anchor": "end", class: "kline-label" });
    const p = maxPrice - ((maxPrice - minPrice) * i) / gridCount;
    label.textContent = p.toFixed(2);
    svg.append(label);
  }

  // Date labels (every ~20 bars)
  const step = Math.max(1, Math.floor(kline.length / 8));
  for (let i = 0; i < kline.length; i += step) {
    const x = xFor(i);
    const label = svgNode("text", { x, y: height - 6, "text-anchor": "middle", class: "kline-label" });
    label.textContent = displayDate(dates[i]).slice(5);
    svg.append(label);
  }

  // Volume labels
  for (let i = 0; i <= 2; i++) {
    const y = pad.top + mainHeight + 8 + (volHeight * i) / 2;
    const label = svgNode("text", { x: pad.left - 6, y: y + 4, "text-anchor": "end", class: "kline-label" });
    label.textContent = i === 0 ? "0" : Math.round((maxVol * i) / 2 / 10000) + "万";
    svg.append(label);
  }

  // Volume bar area separator
  svg.append(svgNode("line", { x1: pad.left, y1: pad.top + mainHeight + 8, x2: width - pad.right, y2: pad.top + mainHeight + 8, class: "kline-grid" }));

  // Calculate MAs
  function ma(data, period) {
    return data.map((_, i) => {
      if (i < period - 1) return NaN;
      let sum = 0;
      for (let j = 0; j < period; j++) sum += data[i - j];
      return sum / period;
    });
  }

  function renderMA(series, className) {
    const valid = [];
    series.forEach((v, i) => {
      if (!isNaN(v)) valid.push({ x: xFor(i), y: yFor(v) });
    });
    if (valid.length < 2) return;
    const d = valid.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
    svg.append(svgNode("path", { d, class: className }));
  }

  const ma5 = ma(closes, 5);
  const ma10 = ma(closes, 10);
  const ma20 = ma(closes, 20);
  renderMA(ma5, "kline-ma5");
  renderMA(ma10, "kline-ma10");
  renderMA(ma20, "kline-ma20");

  // Candles
  for (let i = 0; i < kline.length; i++) {
    const x = xFor(i);
    const o = opens[i];
    const c = closes[i];
    const h = highs[i];
    const l = lows[i];
    const vol = volumes[i];

    const isUp = c >= o;
    const colorClass = isUp ? "kline-candle-up" : "kline-candle-down";

    // Wick
    const wickY1 = yFor(h);
    const wickY2 = yFor(l);
    svg.append(svgNode("line", { x1: x, y1: wickY1, x2: x, y2: wickY2, class: `kline-wick ${colorClass}` }));

    // Candle body
    const bodyY1 = yFor(Math.max(o, c));
    const bodyY2 = yFor(Math.min(o, c));
    const bodyH = Math.max(1, bodyY2 - bodyY1);
    svg.append(svgNode("rect", { x: x - halfCandle, y: bodyY1, width: candleWidth, height: bodyH, class: `kline-candle-body ${colorClass}` }));

    // Volume bar
    const volBaseY = pad.top + mainHeight + 8 + volHeight;
    const volTopY = volYFor(vol);
    const volBarH = volBaseY - volTopY;
    svg.append(svgNode("rect", {
      x: x - halfCandle,
      y: volTopY,
      width: candleWidth,
      height: Math.max(1, volBarH),
      class: `kline-vol ${colorClass}`,
    }));
  }

  // Legend
  const legendG = svgNode("g", { transform: "translate(" + (width - 160) + ", 8)" });
  const legendItems = [
    { label: "MA5", color: "#3498db" },
    { label: "MA10", color: "#e67e22" },
    { label: "MA20", color: "#9b59b6" },
  ];
  legendItems.forEach((item, idx) => {
    const lx = idx * 52;
    const line = svgNode("line", { x1: lx, y1: 6, x2: lx + 14, y2: 6, stroke: item.color, "stroke-width": 2 });
    const text = svgNode("text", { x: lx + 18, y: 10, class: "kline-label" });
    text.textContent = item.label;
    legendG.append(line, text);
  });
  svg.append(legendG);

  // Price label at last candle
  const lastIdx = kline.length - 1;
  const lastPrice = closes[lastIdx];
  const lastX = xFor(lastIdx);
  const lastY = yFor(lastPrice);

  const priceLabel = svgNode("text", {
    x: lastX + 6,
    y: lastY - 4,
    class: "kline-label",
    "font-weight": "bold",
  });
  priceLabel.textContent = lastPrice.toFixed(2);
  svg.append(priceLabel);
}

/* ── Table Rendering ── */

function renderTable(columns, rows) {
  els.tableHead.innerHTML = "";
  els.tableBody.innerHTML = "";

  const tr = document.createElement("tr");
  for (const column of columns) {
    const th = document.createElement("th");
    th.textContent = labelOf(column);
    th.title = column;
    tr.append(th);
  }
  els.tableHead.append(tr);

  for (const row of rows) {
    const rowEl = document.createElement("tr");
    rowEl.style.cursor = "pointer";
    rowEl.addEventListener("click", () => {
      const tsCode = getTsCode(row, columns);
      if (tsCode) showStockDetail(tsCode, row.name || row.stock_name || row["股票名称"] || tsCode);
    });
    for (const column of columns) {
      const td = document.createElement("td");
      td.dataset.col = column;
      td.textContent = row[column] ?? "";
      td.title = row[column] ?? "";
      rowEl.append(td);
    }
    els.tableBody.append(rowEl);
  }
}

function firstValue(row, candidates) {
  for (const key of candidates) {
    if (row[key]) return row[key];
  }
  return "";
}

function renderMobile(columns, rows) {
  els.mobileList.innerHTML = "";

  for (const row of rows) {
    const card = document.createElement("article");
    card.className = "stock-card";
    card.style.cursor = "pointer";
    const tsCode = getTsCode(row, columns);
    card.addEventListener("click", () => {
      if (tsCode) showStockDetail(tsCode, row.name || row.stock_name || row["股票名称"] || tsCode);
    });

    const code = firstValue(row, ["ts_code", "code", "stock_code", "证券代码", "股票代码"]);
    const name = firstValue(row, ["name", "stock_name", "股票名称", "股票简称", "证券简称"]) || code || "--";
    const industry = row.industry || "";

    const header = document.createElement("header");
    const title = document.createElement("div");
    const nameEl = document.createElement("div");
    nameEl.className = "stock-name";
    nameEl.textContent = name;
    const codeEl = document.createElement("div");
    codeEl.className = "stock-code";
    codeEl.textContent = code;
    title.append(nameEl, codeEl);
    header.append(title);

    if (industry) {
      const industryEl = document.createElement("div");
      industryEl.className = "stock-industry";
      industryEl.textContent = industry;
      header.append(industryEl);
    }

    const metricColumns = columns
      .filter((column) => !["source_file", "ts_code", "code", "stock_code", "证券代码", "股票代码", "name", "stock_name", "股票名称", "股票简称", "证券简称", "industry"].includes(column))
      .slice(0, 8);

    const grid = document.createElement("div");
    grid.className = "card-grid";
    for (const column of metricColumns) {
      const metric = document.createElement("div");
      metric.className = "metric";
      const label = document.createElement("span");
      label.textContent = labelOf(column);
      const value = document.createElement("strong");
      value.textContent = row[column] ?? "";
      value.title = row[column] ?? "";
      metric.append(label, value);
      grid.append(metric);
    }

    card.append(header, grid);
    els.mobileList.append(card);
  }
}

function renderData(payload) {
  showListView();
  syncDates(payload);
  state.mode = payload.mode || state.mode;
  state.columns = orderedColumns(payload.columns || []);
  state.rows = payload.rows || [];

  const rowCount = payload.row_count ?? state.rows.length;
  els.emptyState.hidden = rowCount > 0;
  els.emptyState.textContent = "没有匹配的数据";

  if (state.mode === "search") {
    els.modeLabel.textContent = "搜索";
    els.summaryTitle.textContent = payload.query;
    els.summaryMeta.textContent = `${rowCount} 行 · 扫描 ${payload.scanned_csv_count || 0} 个 CSV`;
    els.subtitle.textContent = `搜索结果来自 data 下所有 CSV`;
  } else {
    els.modeLabel.textContent = "日期";
    els.summaryTitle.textContent = displayDate(payload.date);
    const fileText = (payload.files || []).map((file) => file.split("/").pop()).join("，");
    els.summaryMeta.textContent = `${rowCount} 行${fileText ? ` · ${fileText}` : ""}`;
    els.subtitle.textContent = `当前日期 ${displayDate(payload.date)}`;
  }

  renderDateTabs();
  renderTable(state.columns, state.rows);
  renderMobile(state.columns, state.rows);
}

async function loadDate(date) {
  state.mode = "date";
  state.selectedDate = date;
  els.searchInput.value = "";
  renderDateTabs();
  setLoading(displayDate(date));

  try {
    const entry = state.dates.find((item) => item.date === date);
    if (!entry) {
      throw new Error(`日期 ${displayDate(date)} 暂无数据`);
    }
    const payload = await fetchJson(entry.file || `data/dates/${date}.json`);
    if (isEmptyData(payload)) {
      els.summaryTitle.textContent = displayDate(date);
      els.summaryMeta.textContent = "该日期无股票数据";
      els.tableHead.innerHTML = "";
      els.tableBody.innerHTML = "";
      els.mobileList.innerHTML = "";
      els.emptyState.hidden = false;
      els.emptyState.textContent = "该日期没有匹配的股票数据";
      return;
    }
    renderData({
      ...payload,
      dates: state.dates,
      latest_date: state.latestDate,
    });
  } catch (error) {
    setError(error);
  }
}

async function loadSearchIndex() {
  if (!state.searchIndex) {
    const indexPath = state.manifest?.search_index || "data/search_index.json";
    state.searchIndex = await fetchJson(indexPath);
  }
  return state.searchIndex;
}

async function runSearch(query) {
  state.mode = "search";
  renderDateTabs();
  setLoading(query);

  try {
    const index = await loadSearchIndex();
    const columns = index.columns || [];
    const rows = (index.rows || []).filter((row) => rowMatches(row, query, columns));
    renderData({
      mode: "search",
      query,
      dates: state.dates,
      latest_date: state.latestDate,
      columns,
      rows,
      row_count: rows.length,
      scanned_csv_count: index.scanned_csv_count || 0,
    });
  } catch (error) {
    setError(error);
  }
}

async function init() {
  setLoading("加载日期");
  try {
    const payload = await fetchJson("data/manifest.json");
    state.manifest = payload;
    
    if (!payload.latest_date || !payload.dates || payload.dates.length === 0) {
      els.subtitle.textContent = "请先生成数据，在项目根目录运行：python export_web_data.py";
      els.summaryTitle.textContent = "暂无数据";
      els.summaryMeta.textContent = "运行 export_web_data.py 生成数据后再刷新页面";
      els.emptyState.hidden = false;
      els.emptyState.textContent = "尚未生成数据文件，请运行数据导出命令";
      return;
    }
    
    syncDates(payload);
    await Promise.all([loadDate(payload.latest_date), loadIndustryTrends()]);
  } catch (error) {
    setError(error);
  }
}

els.searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = els.searchInput.value.trim();
  if (query) {
    runSearch(query);
  } else if (state.selectedDate) {
    loadDate(state.selectedDate);
  }
});

els.clearSearch.addEventListener("click", () => {
  els.searchInput.value = "";
  if (state.selectedDate) {
    loadDate(state.selectedDate);
  }
});

init();
