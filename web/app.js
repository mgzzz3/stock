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
  dateColumns: [],
  dateRows: [],
  dateDataDate: null,
  selectedIndustry: null,
  listFilter: "all",
  activeTab: "mainline",  // "mainline" | "b1" | "strategy"
  stockListSource: "b1",  // "b1" | "mainline" | "strategy"
  mainlineData: null,
  conceptData: null,
  focusStocks: [],
  detailReturnTarget: null,
  detailCase: null,
  klineView: null,
  strategyData: null,
  activeStrategyId: null,
  strategyCurveMode: "walk_forward",
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
  industryBack: document.querySelector("#industryBack"),
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
  klineHoverDate: document.querySelector("#klineHoverDate"),
  klineHoverOpen: document.querySelector("#klineHoverOpen"),
  klineHoverClose: document.querySelector("#klineHoverClose"),
  klineHoverChange: document.querySelector("#klineHoverChange"),
  klineZoomStatus: document.querySelector("#klineZoomStatus"),
  klineZoomOut: document.querySelector("#klineZoomOut"),
  klineZoomReset: document.querySelector("#klineZoomReset"),
  klineZoomIn: document.querySelector("#klineZoomIn"),
  detailReturns: document.querySelector("#detailReturns"),
  detailReturnTitle: document.querySelector("#detailReturnTitle"),
  detailReturnNote: document.querySelector("#detailReturnNote"),
  detailLoading: document.querySelector("#detailLoading"),
  detailError: document.querySelector("#detailError"),
  industryPanel: document.querySelector(".industry-panel"),
  predictionToolbar: document.querySelector("#predictionToolbar"),
  predictionTitle: document.querySelector("#predictionTitle"),
  predictionMeta: document.querySelector("#predictionMeta"),
  predictionOnly: document.querySelector("#predictionOnly"),
  showAllStocks: document.querySelector("#showAllStocks"),
  /* Main line monitoring */
  mainlinePanel: document.querySelector("#mainlinePanel"),
  mainlineSubtitle: document.querySelector("#mainlineSubtitle"),
  mainlineBadge: document.querySelector("#mainlineBadge"),
  signalCard: document.querySelector("#signalCard"),
  signalMeta: document.querySelector("#signalMeta"),
  mainlineMeta: document.querySelector("#mainlineMeta"),
  mainlineCurrent: document.querySelector("#mainlineCurrent"),
  mainlineTableBody: document.querySelector("#mainlineTableBody"),
  conceptSubtitle: document.querySelector("#conceptSubtitle"),
  conceptTableBody: document.querySelector("#conceptTableBody"),
  focusStockSection: document.querySelector("#focusStockSection"),
  focusStockMeta: document.querySelector("#focusStockMeta"),
  focusStockTableBody: document.querySelector("#focusStockTableBody"),
  /* Tabs */
  viewTabs: document.querySelector("#viewTabs"),
  tabMainline: document.querySelector("#tabMainline"),
  tabStrategy: document.querySelector("#tabStrategy"),
  stockWorkspace: document.querySelector("#stockWorkspace"),
  /* Strategy decision dashboard */
  strategySubtitle: document.querySelector("#strategySubtitle"),
  strategyAsOf: document.querySelector("#strategyAsOf"),
  strategyRiskNotice: document.querySelector("#strategyRiskNotice"),
  strategyCards: document.querySelector("#strategyCards"),
  strategyDetail: document.querySelector("#strategyDetail"),
  strategyDetailTitle: document.querySelector("#strategyDetailTitle"),
  strategyDetailStatus: document.querySelector("#strategyDetailStatus"),
  strategyThesis: document.querySelector("#strategyThesis"),
  strategyEvidence: document.querySelector("#strategyEvidence"),
  strategyMetrics: document.querySelector("#strategyMetrics"),
  strategyCredibilityLevel: document.querySelector("#strategyCredibilityLevel"),
  strategyCredibilityGrid: document.querySelector("#strategyCredibilityGrid"),
  strategyCredibilityNote: document.querySelector("#strategyCredibilityNote"),
  strategyCurve: document.querySelector("#strategyCurve"),
  strategyCurveMeta: document.querySelector("#strategyCurveMeta"),
  strategyCurveMethod: document.querySelector("#strategyCurveMethod"),
  strategyWalkForwardMode: document.querySelector("#strategyWalkForwardMode"),
  strategyFullSampleMode: document.querySelector("#strategyFullSampleMode"),
  strategyRules: document.querySelector("#strategyRules"),
  strategyRecommendationTitle: document.querySelector("#strategyRecommendationTitle"),
  strategyRecommendationNote: document.querySelector("#strategyRecommendationNote"),
  strategyRecommendationCount: document.querySelector("#strategyRecommendationCount"),
  strategyRecommendationBody: document.querySelector("#strategyRecommendationBody"),
  strategyTableWrap: document.querySelector("#strategyTableWrap"),
  strategyRecommendationEmpty: document.querySelector("#strategyRecommendationEmpty"),
  strategyHistoryNote: document.querySelector("#strategyHistoryNote"),
  strategyHistoryCount: document.querySelector("#strategyHistoryCount"),
  strategyHistoryBody: document.querySelector("#strategyHistoryBody"),
  strategyHistoryTableWrap: document.querySelector("#strategyHistoryTableWrap"),
  strategyHistoryEmpty: document.querySelector("#strategyHistoryEmpty"),
  strategyError: document.querySelector("#strategyError"),
};

function syncTabPanels() {
  const showMainlineStockList = state.activeTab === "mainline" && state.stockListSource === "mainline";
  const showStrategyStockDetail = state.activeTab === "strategy" && state.stockListSource === "strategy";
  els.tabMainline.hidden = state.activeTab !== "mainline" || showMainlineStockList;
  els.tabStrategy.hidden = state.activeTab !== "strategy" || showStrategyStockDetail;
  els.stockWorkspace.hidden = state.activeTab !== "b1" && !showMainlineStockList && !showStrategyStockDetail;
}

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
  "prediction_rank",
  "prob_up",
  "reasons",
  "close",
  "vol_ratio",
  "j",
  "ma60",
  "trend_short",
  "bull_bear",
  "last_signal",
  "days_since",
];

const hiddenColumns = new Set(["source_file", "prediction_source_file"]);

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
  prediction_rank: "预测排名",
  prob_up: "上涨概率",
  reasons: "预测依据",
  next_trade_date: "预测交易日",
  prediction_source_file: "预测来源",
  close: "收盘",
  pct_chg: "涨跌幅",
  amount: "成交额",
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
  els.industryPanel.hidden = state.stockListSource !== "b1" || state.mode === "search";
  els.summaryTitle.textContent = text;
  els.summaryMeta.textContent = "加载中";
  els.tableHead.innerHTML = "";
  els.tableBody.innerHTML = "";
  els.mobileList.innerHTML = "";
  els.emptyState.hidden = true;
}

function setError(error) {
  state.stockListSource = "b1";
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
    button.className = item.date === state.selectedDate && ["date", "industry"].includes(state.mode) ? "active" : "";
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

function normalizeIndustry(value) {
  const industry = String(value ?? "").trim();
  return industry || "未分类";
}

function previousTrendDate(dates, selectedDate) {
  const index = dates.indexOf(selectedDate);
  return index > 0 ? dates[index - 1] : null;
}

function countForDate(row, date) {
  return countMap(row).get(date) || 0;
}

function industryPayloadForDate(payload, selectedDate) {
  if (!payload || !selectedDate) return payload;

  const allDates = payload.dates || [];
  const chartDates = allDates.filter((date) => date <= selectedDate);
  const dates = chartDates.length ? chartDates : allDates;
  const previousDate = previousTrendDate(allDates, selectedDate);

  const rows = (payload.industries || []).map((row) => {
    const latestCount = countForDate(row, selectedDate);
    const previousCount = previousDate ? countForDate(row, previousDate) : 0;
    return {
      ...row,
      latest_count: latestCount,
      previous_count: previousCount,
      change: latestCount - previousCount,
      is_new_latest: latestCount > 0 && previousCount === 0,
      is_removed_latest: latestCount === 0 && previousCount > 0,
      counts: (row.counts || []).filter((item) => !dates.length || dates.includes(item.date)),
    };
  });

  const latestRows = rows
    .filter((row) => row.latest_count > 0)
    .sort((a, b) => b.latest_count - a.latest_count || b.change - a.change || a.industry.localeCompare(b.industry, "zh-Hans-CN"));
  const removedLatest = rows
    .filter((row) => row.is_removed_latest)
    .sort((a, b) => b.previous_count - a.previous_count || a.industry.localeCompare(b.industry, "zh-Hans-CN"));

  return {
    ...payload,
    dates,
    latest_date: selectedDate,
    previous_date: previousDate,
    industries: rows,
    latest: latestRows,
    new_latest: latestRows.filter((row) => row.is_new_latest),
    removed_latest: removedLatest,
  };
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
    legend.dataset.industry = row.industry;
    legend.title = `查看 ${displayDate(state.selectedDate || payload.latest_date)} ${row.industry} 股票`;
    legend.addEventListener("click", () => showIndustryStocks(row.industry, state.selectedDate || payload.latest_date));
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
    item.dataset.industry = row.industry;
    item.title = `查看 ${displayDate(state.selectedDate || payload.latest_date)} ${row.industry} 股票`;
    item.addEventListener("click", () => showIndustryStocks(row.industry, state.selectedDate || payload.latest_date));
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
  const rows = payload.latest || [];

  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.title = `查看 ${displayDate(state.selectedDate || payload.latest_date)} ${row.industry} 股票`;
    tr.addEventListener("click", () => showIndustryStocks(row.industry, state.selectedDate || payload.latest_date));

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
  const displayPayload = industryPayloadForDate(payload, state.selectedDate || payload.latest_date);
  const latestRows = displayPayload.latest || [];
  const totalIndustries = latestRows.length;
  const totalStocks = latestRows.reduce((sum, row) => sum + Number(row.latest_count || 0), 0);
  const newCount = (displayPayload.new_latest || []).length;
  const removedCount = (displayPayload.removed_latest || []).length;

  els.industrySubtitle.textContent = `${displayDate(displayPayload.latest_date)} 行业分布`;
  els.industryStat.textContent = `${totalIndustries} 个行业 · ${totalStocks} 只股票`;
  els.industryChartMeta.textContent = `当日 Top 8 · ${displayPayload.dates?.length || 0} 天`;
  els.industryChangeMeta.textContent = displayPayload.previous_date
    ? `${displayDate(displayPayload.previous_date)} → ${displayDate(displayPayload.latest_date)}`
    : displayDate(displayPayload.latest_date);

  renderIndustryChart(displayPayload);
  renderNewIndustries(displayPayload);
  renderRemovedIndustries(displayPayload);
  renderIndustryTable(displayPayload);

  if (newCount > 0 || removedCount > 0) {
    els.industrySubtitle.textContent = `${displayDate(displayPayload.latest_date)} 新进 ${newCount} 个 · 消失 ${removedCount} 个`;
  }
}

function rowIndustry(row) {
  return normalizeIndustry(row.industry);
}

function stockDisplayName(row, fallback) {
  return row.name || row.stock_name || row["股票名称"] || row["股票简称"] || row["证券简称"] || fallback;
}

function showIndustryStocks(industry, date = state.selectedDate) {
  const targetIndustry = normalizeIndustry(industry);
  const columns = state.dateColumns.length ? state.dateColumns : state.columns;
  const rows = (state.dateRows.length ? state.dateRows : state.rows).filter((row) => rowIndustry(row) === targetIndustry);

  state.stockListSource = "b1";
  state.mode = "industry";
  state.selectedIndustry = targetIndustry;
  state.columns = columns;
  state.rows = rows;
  els.searchInput.value = "";
  els.industryBack.hidden = false;
  els.industryBack.textContent = "← 返回行业列表";
  els.industryPanel.hidden = true;
  els.predictionToolbar.hidden = true;
  els.detailPanel.hidden = true;
  els.listPanel.hidden = false;
  els.modeLabel.textContent = "行业";
  els.summaryTitle.textContent = targetIndustry;
  els.summaryMeta.textContent = `${displayDate(date)} · ${rows.length} 只股票 · 点击股票进入详情`;
  els.subtitle.textContent = `当前日期 ${displayDate(date)} · 行业 ${targetIndustry}`;
  els.emptyState.hidden = rows.length > 0;
  els.emptyState.textContent = `${displayDate(date)} 没有行业为 ${targetIndustry} 的股票`;
  renderDateTabs();
  renderTable(columns, rows);
  renderMobile(columns, rows);
}

function showMainlineDashboard(scrollTarget = els.mainlinePanel) {
  state.mode = "date";
  state.selectedIndustry = null;
  state.stockListSource = "b1";
  state.detailReturnTarget = null;
  els.searchInput.value = "";
  els.industryBack.hidden = true;
  els.listPanel.hidden = true;
  els.detailPanel.hidden = true;
  els.industryPanel.hidden = true;
  els.predictionToolbar.hidden = true;
  syncTabPanels();
  els.subtitle.textContent = `主线监控 · ${displayDate(state.selectedDate)}`;
  scrollTarget?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function backToIndustryList() {
  if (state.stockListSource === "mainline") {
    showMainlineDashboard();
    return;
  }

  if (state.selectedDate) {
    loadDate(state.selectedDate);
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
  els.listPanel.hidden = state.activeTab !== state.stockListSource;
  els.industryPanel.hidden = state.activeTab !== "b1" || state.mode === "search" || state.mode === "industry";
}

function renderCachedDateData() {
  renderData({
    mode: "date",
    date: state.selectedDate,
    dates: state.dates,
    latest_date: state.latestDate,
    columns: state.dateColumns,
    rows: state.dateRows,
  });
}

const KLINE_MIN_VISIBLE_DAYS = 20;

function maxKlineZoomLevel(total, minimumVisible = KLINE_MIN_VISIBLE_DAYS) {
  let level = 0;
  while (Math.ceil(total / (2 ** level)) > minimumVisible) {
    level += 1;
  }
  return level;
}

function klineVisibleCount(total, zoomLevel, minimumVisible = KLINE_MIN_VISIBLE_DAYS) {
  if (!total) return 0;
  return Math.min(total, Math.max(minimumVisible, Math.ceil(total / (2 ** zoomLevel))));
}

function klineCaseIndexes(view) {
  if (!view?.strategyCase) return [];
  const dates = view.kline.map((item) => String(item.trade_date || ""));
  return [
    view.strategyCase.signal_date,
    view.strategyCase.entry_date,
    view.strategyCase.exit_date,
  ]
    .map((date) => dates.indexOf(String(date || "")))
    .filter((index) => index >= 0);
}

function minimumKlineVisibleDays(view) {
  const indexes = klineCaseIndexes(view);
  if (indexes.length < 2) return KLINE_MIN_VISIBLE_DAYS;
  const caseSpan = Math.max(...indexes) - Math.min(...indexes) + 1;
  return Math.min(view.kline.length, Math.max(KLINE_MIN_VISIBLE_DAYS, caseSpan + 10));
}

function klineViewWindow(view) {
  const minimumVisible = minimumKlineVisibleDays(view);
  const visible = klineVisibleCount(view.kline.length, view.zoomLevel, minimumVisible);
  const caseIndexes = klineCaseIndexes(view);
  if (caseIndexes.length < 2) {
    return { visible, start: Math.max(0, view.kline.length - visible), minimumVisible };
  }
  const caseCenter = (Math.min(...caseIndexes) + Math.max(...caseIndexes)) / 2;
  const start = Math.max(0, Math.min(
    view.kline.length - visible,
    Math.round(caseCenter - (visible - 1) / 2),
  ));
  return { visible, start, minimumVisible };
}

function updateKlineZoomControls() {
  const view = state.klineView;
  const total = view?.kline?.length || 0;
  const level = view?.zoomLevel || 0;
  const minimumVisible = view ? minimumKlineVisibleDays(view) : KLINE_MIN_VISIBLE_DAYS;
  const visible = klineVisibleCount(total, level, minimumVisible);
  const maxLevel = maxKlineZoomLevel(total, minimumVisible);

  els.klineZoomOut.disabled = !total || level === 0;
  els.klineZoomReset.disabled = !total || level === 0;
  els.klineZoomIn.disabled = !total || level >= maxLevel;
  const zoomRatio = visible ? total / visible : 1;
  const zoomLabel = zoomRatio <= 1
    ? "全部"
    : `${zoomRatio.toFixed(zoomRatio >= 10 ? 0 : 1)} 倍`;
  els.klineZoomStatus.textContent = total
    ? `显示 ${visible} / ${total} 个交易日 · ${zoomLabel}`
    : "等待日线数据";
}

function renderKlineView() {
  const view = state.klineView;
  if (!view) {
    updateKlineZoomControls();
    return;
  }
  const window = klineViewWindow(view);
  renderKlineChart(
    view.kline,
    view.stockLabel,
    view.signalDates,
    view.strategyCase,
    window.start,
    window.visible,
  );
  updateKlineZoomControls();
}

function setKlineZoom(nextLevel) {
  const view = state.klineView;
  if (!view) return;
  const maxLevel = maxKlineZoomLevel(view.kline.length, minimumKlineVisibleDays(view));
  view.zoomLevel = Math.max(0, Math.min(maxLevel, nextLevel));
  renderKlineView();
}

els.klineZoomOut.addEventListener("click", () => setKlineZoom((state.klineView?.zoomLevel || 0) - 1));
els.klineZoomReset.addEventListener("click", () => setKlineZoom(0));
els.klineZoomIn.addEventListener("click", () => setKlineZoom((state.klineView?.zoomLevel || 0) + 1));

function showStockDetail(tsCode, name, options = {}) {
  state.detailReturnTarget = options.returnTarget || null;
  state.detailCase = options.strategyCase || null;
  state.klineView = null;
  updateKlineZoomControls();
  syncTabPanels();
  els.listPanel.hidden = true;
  els.industryPanel.hidden = true;
  els.predictionToolbar.hidden = true;
  els.detailPanel.hidden = false;
  els.detailName.textContent = name || "--";
  els.detailCode.textContent = tsCode;
  els.detailLoading.hidden = false;
  els.detailError.hidden = true;
  els.klineChart.innerHTML = "";
  updateKlineHoverInfo();
  els.detailReturns.innerHTML = "";
  els.detailReturnTitle.textContent = state.detailCase ? "策略历史案例" : "B标记收益";
  els.detailReturnNote.textContent = state.detailCase
    ? `${state.detailCase.strategy_name || "策略"} · ${state.detailCase.evidence_label || "历史回测"}`
    : "近20个交易日内出现的B，按次日开盘买入计算至最新收盘。";
  els.detailMeta.textContent = "获取日线数据中…";

  loadStockDetailData(tsCode)
    .then((data) => {
      els.detailLoading.hidden = true;
      if (data.error) {
        els.detailError.hidden = false;
        els.detailError.textContent = data.error;
        return;
      }
      els.detailName.textContent = data.name || name || "--";
      const signalDates = data.signal_dates || state.manifest?.signal_dates?.[data.ts_code] || state.manifest?.signal_dates?.[tsCode] || [];
      const signalCount = signalDates.length;
      els.detailMeta.textContent = state.detailCase
        ? `${data.count} 个交易日 · 信号 ${displayDate(state.detailCase.signal_date)} · 扣费收益 ${strategyMetricValue(state.detailCase.net_return_pct, "%")}`
        : `${data.count} 个交易日${signalCount ? ` · ${signalCount} 个B标记` : ""}`;
      state.klineView = {
        kline: data.kline || [],
        stockLabel: data.name || tsCode,
        signalDates: state.detailCase ? [] : signalDates,
        strategyCase: state.detailCase,
        zoomLevel: 0,
      };
      renderKlineView();
      if (state.detailCase) {
        renderStrategyCaseSummary(state.detailCase);
      } else {
        renderSignalReturns(data.kline, signalDates);
      }
    })
    .catch((err) => {
      els.detailLoading.hidden = true;
      els.detailError.hidden = false;
      els.detailError.textContent = `请求失败: ${err.message}。请重新运行 export_web_data.py 导出详情数据；本地预览也可以使用 h5_server.py 启动服务。`;
    });
}

function backToList() {
  if (state.detailReturnTarget === "strategy") {
    state.detailCase = null;
    state.stockListSource = "b1";
    els.detailPanel.hidden = true;
    syncTabPanels();
    els.strategyDetail?.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  if (state.detailReturnTarget === "focus-stocks") {
    showMainlineDashboard(els.focusStockSection);
    return;
  }
  showListView();
  updatePredictionToolbar();
}

els.detailBack.addEventListener("click", backToList);
els.industryBack.addEventListener("click", backToIndustryList);

/* ── Candlestick Chart (SVG) ── */

function formatPercent(value) {
  if (!Number.isFinite(value)) return "--";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function updateKlineHoverInfo(item, previousItem) {
  if (!item) {
    els.klineHoverDate.textContent = "--";
    els.klineHoverOpen.textContent = "--";
    els.klineHoverClose.textContent = "--";
    els.klineHoverChange.textContent = "--";
    els.klineHoverChange.className = "";
    return;
  }

  const open = Number(item.open);
  const close = Number(item.close);
  const reportedPreClose = Number(item.pre_close);
  const previousClose = Number(previousItem?.close);
  const preClose = reportedPreClose > 0 ? reportedPreClose : previousClose;
  const change = Number.isFinite(close) && preClose > 0 ? ((close - preClose) / preClose) * 100 : NaN;

  els.klineHoverDate.textContent = displayDate(item.trade_date);
  els.klineHoverOpen.textContent = Number.isFinite(open) ? open.toFixed(2) : "--";
  els.klineHoverClose.textContent = Number.isFinite(close) ? close.toFixed(2) : "--";
  els.klineHoverChange.textContent = formatPercent(change);
  els.klineHoverChange.className = change > 0 ? "return-up" : change < 0 ? "return-down" : "return-flat";
}

function signalDateSet(signalDates) {
  return new Set((signalDates || []).map((date) => String(date).trim()).filter(Boolean));
}

function recentSignalIndexes(kline, signalDates, windowSize = 20) {
  const signals = signalDateSet(signalDates);
  const start = Math.max(0, kline.length - windowSize);
  return kline
    .map((item, index) => ({ item, index }))
    .filter(({ item, index }) => index >= start && signals.has(String(item.trade_date || "")));
}

function renderSignalReturns(kline, signalDates) {
  els.detailReturns.innerHTML = "";

  if (!kline || kline.length < 2) {
    els.detailReturns.textContent = "K线数据不足，无法计算。";
    return;
  }

  const signals = recentSignalIndexes(kline, signalDates);
  if (!signals.length) {
    els.detailReturns.textContent = "近20个交易日无B标记。";
    return;
  }

  const latest = kline[kline.length - 1];
  const latestClose = Number(latest.close);

  for (const { item, index } of signals.reverse()) {
    const row = document.createElement("div");
    row.className = "detail-return-row";

    const date = document.createElement("span");
    date.textContent = displayDate(item.trade_date);

    const value = document.createElement("strong");
    if (index + 1 >= kline.length) {
      value.textContent = "待次日开盘";
      value.className = "return-pending";
    } else {
      const buyOpen = Number(kline[index + 1].open);
      const pct = ((latestClose - buyOpen) / buyOpen) * 100;
      value.textContent = formatPercent(pct);
      value.title = `买入价 ${buyOpen.toFixed(2)}，最新收盘 ${latestClose.toFixed(2)}`;
      value.className = pct > 0 ? "return-up" : pct < 0 ? "return-down" : "return-flat";
    }

    row.append(date, value);
    els.detailReturns.append(row);
  }
}

function renderStrategyCaseSummary(strategyCase) {
  els.detailReturns.innerHTML = "";
  const rows = [
    ["信号日", displayDate(strategyCase.signal_date)],
    ["买入日", displayDate(strategyCase.entry_date)],
    ["退出日", displayDate(strategyCase.exit_date)],
    ["扣费收益", strategyMetricValue(strategyCase.net_return_pct, "%")],
    ["证据口径", strategyCase.evidence_label || "--"],
    ["退出方式", strategyCase.exit_reason || "--"],
  ];
  for (const [label, value] of rows) {
    const item = document.createElement("div");
    item.className = "detail-return-row";
    const labelNode = document.createElement("span");
    labelNode.textContent = label;
    const valueNode = document.createElement("strong");
    valueNode.textContent = value;
    if (label === "扣费收益") {
      valueNode.className = Number(strategyCase.net_return_pct) >= 0 ? "return-up" : "return-down";
    }
    item.append(labelNode, valueNode);
    els.detailReturns.append(item);
  }
  const reasons = document.createElement("div");
  reasons.className = "detail-case-reasons";
  const title = document.createElement("strong");
  title.textContent = "信号理由";
  const list = document.createElement("ul");
  for (const reason of strategyCase.reasons || []) {
    const item = document.createElement("li");
    item.textContent = reason;
    list.append(item);
  }
  reasons.append(title, list);
  els.detailReturns.append(reasons);
}

function renderKlineChart(kline, stockLabel, signalDates = [], strategyCase = null, viewStart = 0, viewCount = null) {
  const svg = els.klineChart;
  svg.innerHTML = "";

  if (!kline || kline.length < 2) {
    updateKlineHoverInfo();
    const t = svgNode("text", { x: 400, y: 200, "text-anchor": "middle", class: "kline-label" });
    t.textContent = "K线数据不足";
    svg.append(t);
    return;
  }

  const fullKline = kline;
  const safeViewStart = Math.max(0, Math.min(fullKline.length - 2, Number(viewStart) || 0));
  const requestedCount = Number(viewCount) || (fullKline.length - safeViewStart);
  const safeViewCount = Math.max(2, Math.min(fullKline.length - safeViewStart, requestedCount));
  kline = fullKline.slice(safeViewStart, safeViewStart + safeViewCount);

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
  const fullCloses = fullKline.map((d) => Number(d.close));
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

  const ma5 = ma(fullCloses, 5).slice(safeViewStart, safeViewStart + safeViewCount);
  const ma10 = ma(fullCloses, 10).slice(safeViewStart, safeViewStart + safeViewCount);
  const ma20 = ma(fullCloses, 20).slice(safeViewStart, safeViewStart + safeViewCount);
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

  // B markers for screening dates
  const signalIndexes = recentSignalIndexes(kline, signalDates, kline.length);
  for (const { item, index } of signalIndexes) {
    const x = xFor(index);
    const y = yFor(Number(item.low)) + 18;
    const marker = svgNode("text", {
      x,
      y: Math.min(pad.top + mainHeight - 4, y),
      "text-anchor": "middle",
      class: "kline-b-marker",
    });
    marker.textContent = "B";
    svg.append(marker);
  }

  if (strategyCase) {
    const caseMarkers = [
      [strategyCase.signal_date, "S", "case-signal"],
      [strategyCase.entry_date, "买", "case-entry"],
      [strategyCase.exit_date, "卖", "case-exit"],
    ];
    for (const [date, label, className] of caseMarkers) {
      const index = dates.indexOf(String(date || ""));
      if (index < 0) continue;
      const marker = svgNode("text", {
        x: xFor(index),
        y: Math.max(pad.top + 12, yFor(highs[index]) - 8),
        "text-anchor": "middle",
        class: `kline-case-marker ${className}`,
      });
      marker.textContent = label;
      svg.append(marker);
    }
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

  const hoverLine = svgNode("line", {
    y1: pad.top,
    y2: pad.top + mainHeight + 8 + volHeight,
    class: "kline-hover-line",
    visibility: "hidden",
  });
  const hoverTarget = svgNode("rect", {
    x: pad.left,
    y: pad.top,
    width: plotW,
    height: mainHeight + 8 + volHeight,
    class: "kline-hover-target",
  });

  const selectKlineAt = (clientX) => {
    const point = svg.createSVGPoint();
    point.x = clientX;
    point.y = 0;
    const chartX = point.matrixTransform(svg.getScreenCTM().inverse()).x;
    const index = Math.max(0, Math.min(kline.length - 1, Math.round(((chartX - pad.left) / plotW) * (kline.length - 1))));
    const x = xFor(index);
    hoverLine.setAttribute("x1", x);
    hoverLine.setAttribute("x2", x);
    hoverLine.setAttribute("visibility", "visible");
    updateKlineHoverInfo(kline[index], kline[index - 1]);
  };

  hoverTarget.addEventListener("pointermove", (event) => selectKlineAt(event.clientX));
  hoverTarget.addEventListener("pointerleave", () => {
    hoverLine.setAttribute("visibility", "hidden");
    updateKlineHoverInfo(kline[lastIdx], kline[lastIdx - 1]);
  });

  svg.append(hoverLine, hoverTarget);
  updateKlineHoverInfo(kline[lastIdx], kline[lastIdx - 1]);
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
      if (tsCode) showStockDetail(tsCode, stockDisplayName(row, tsCode));
    });
    for (const column of columns) {
      const td = document.createElement("td");
      td.dataset.col = column;
      const rawValue = row[column] ?? "";
      if (column === "prob_up" && rawValue !== "") {
        const probability = Number(rawValue);
        const badge = document.createElement("span");
        badge.className = "prediction-probability";
        badge.textContent = Number.isFinite(probability) ? `${(probability * 100).toFixed(1)}%` : rawValue;
        if (Number.isFinite(probability) && probability >= 0.6) badge.classList.add("prediction-high");
        td.append(badge);
      } else {
        td.textContent = rawValue;
      }
      td.title = String(rawValue);
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
      if (tsCode) showStockDetail(tsCode, stockDisplayName(row, tsCode));
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
      if (column === "reasons") metric.classList.add("prediction-reasons");
      if (column === "prob_up") metric.classList.add("prediction-probability-metric");
      const label = document.createElement("span");
      label.textContent = labelOf(column);
      const value = document.createElement("strong");
      const rawValue = row[column] ?? "";
      if (column === "prob_up" && rawValue !== "") {
        const probability = Number(rawValue);
        const badge = document.createElement("span");
        badge.className = "prediction-probability";
        badge.textContent = Number.isFinite(probability) ? `${(probability * 100).toFixed(1)}%` : rawValue;
        if (Number.isFinite(probability) && probability >= 0.6) badge.classList.add("prediction-high");
        value.append(badge);
      } else {
        value.textContent = rawValue;
      }
      value.title = String(rawValue);
      metric.append(label, value);
      grid.append(metric);
    }

    card.append(header, grid);
    els.mobileList.append(card);
  }
}

function hasPrediction(row) {
  return row.prediction_rank !== "" && row.prediction_rank !== null && row.prediction_rank !== undefined;
}

function predictionRows(rows) {
  return rows.filter(hasPrediction);
}

function updatePredictionToolbar() {
  const predictions = predictionRows(state.dateRows);
  const isDateView = state.mode === "date";
  els.predictionToolbar.hidden = !isDateView || predictions.length === 0;
  if (!isDateView || predictions.length === 0) return;

  const targetDates = [...new Set(predictions.map((row) => row.next_trade_date).filter(Boolean))];
  const targetText = targetDates.length === 1 ? ` · 预测 ${displayDate(String(targetDates[0]))}` : "";
  els.predictionMeta.textContent = `${predictions.length} 只${targetText} · 当日列表共 ${state.dateRows.length} 只`;
  els.predictionOnly.classList.toggle("active", state.listFilter === "predictions");
  els.showAllStocks.classList.toggle("active", state.listFilter === "all");
  els.predictionOnly.setAttribute("aria-pressed", String(state.listFilter === "predictions"));
  els.showAllStocks.setAttribute("aria-pressed", String(state.listFilter === "all"));
}

function applyListFilter(filter) {
  if (!state.dateRows.length) return;
  state.listFilter = filter === "predictions" ? "predictions" : "all";
  state.rows = state.listFilter === "predictions" ? predictionRows(state.dateRows) : state.dateRows;
  els.emptyState.hidden = state.rows.length > 0;
  els.summaryMeta.textContent = state.listFilter === "predictions"
    ? `${state.rows.length} 条次日预测 · 当日列表共 ${state.dateRows.length} 只`
    : `${state.rows.length} 条当日记录 · 其中 ${predictionRows(state.dateRows).length} 条有次日预测`;
  updatePredictionToolbar();
  renderTable(state.columns, state.rows);
  renderMobile(state.columns, state.rows);
  els.listPanel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderData(payload) {
  syncDates(payload);
  state.stockListSource = "b1";
  state.mode = payload.mode || state.mode;
  state.selectedIndustry = null;
  els.industryBack.hidden = true;
  showListView();
  state.columns = orderedColumns(payload.columns || []);
  const payloadRows = payload.rows || [];
  state.rows = payloadRows;
  if (state.mode === "date") {
    state.dateColumns = state.columns;
    state.dateRows = payloadRows;
    state.dateDataDate = payload.date || state.selectedDate;
    state.listFilter = predictionRows(payloadRows).length ? "predictions" : "all";
    state.rows = state.listFilter === "predictions" ? predictionRows(payloadRows) : payloadRows;
  } else {
    state.listFilter = "all";
  }

  const rowCount = state.rows.length;
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
  updatePredictionToolbar();
  if (state.mode === "date" && state.industryTrends) {
    renderIndustryPanel(state.industryTrends);
  }
  renderTable(state.columns, state.rows);
  renderMobile(state.columns, state.rows);
}

async function loadDate(date) {
  state.stockListSource = "b1";
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

async function ensureDateData(date) {
  if (state.dateDataDate === date && state.dateRows.length) return;
  const entry = state.dates.find((item) => item.date === date);
  if (!entry) throw new Error(`日期 ${displayDate(date)} 暂无数据`);
  const payload = await fetchJson(entry.file || `data/dates/${date}.json`);
  if (isEmptyData(payload)) {
    state.dateColumns = [];
    state.dateRows = [];
    state.dateDataDate = date;
    return;
  }
  state.dateColumns = orderedColumns(payload.columns || []);
  state.dateRows = payload.rows || [];
  state.dateDataDate = payload.date || date;
}

async function loadSearchIndex() {
  if (!state.searchIndex) {
    const indexPath = state.manifest?.search_index || "data/search_index.json";
    state.searchIndex = await fetchJson(indexPath);
  }
  return state.searchIndex;
}

async function runSearch(query) {
  state.stockListSource = "b1";
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

/* ── Main Line Monitoring ── */

function displayMainLineBadge(level) {
  const badge = els.mainlineBadge;
  const labels = {
    strong: "✅ 主线确认",
    emerging: "🟡 主线萌芽",
    candidate: "🔵 潜在主线",
    none: "⚪ 无明显主线",
  };
  const cls = {
    strong: "signal-strong",
    emerging: "signal-emerging",
    candidate: "signal-candidate",
    none: "signal-none",
  };
  badge.textContent = labels[level] || "--";
  badge.className = "mainline-badge";
  if (cls[level]) badge.classList.add(cls[level]);
}

function displayScore(score) {
  if (score >= 0.7) return `<span class="score-high">${score.toFixed(3)}</span>`;
  if (score >= 0.5) return `<span class="score-mid">${score.toFixed(3)}</span>`;
  return `<span class="score-low">${score.toFixed(3)}</span>`;
}

function displayReturn(val, unit = "%") {
  if (val == null) return "--";
  const cls = val > 0 ? "return-up" : val < 0 ? "return-down" : "";
  const sign = val > 0 ? "+" : "";
  return `<span class="${cls}">${sign}${val.toFixed(2)}${unit}</span>`;
}

function renderSignalCard(signal) {
  els.signalCard.innerHTML = "";
  if (!signal) {
    els.signalCard.innerHTML = '<div class="signal-loading">暂无信号数据</div>';
    return;
  }

  const summary = document.createElement("div");
  summary.className = `signal-summary ${signal.confirmation_level || "none"}`;
  summary.textContent = signal.summary || "--";
  els.signalCard.append(summary);

  els.signalMeta.textContent = `强度 ${signal.strength}/2 · 连续${signal.consecutive_days}天`;
}

function renderCurrentMainline(sectors, signal) {
  els.mainlineCurrent.innerHTML = "";
  if (!sectors || !sectors.length) {
    els.mainlineCurrent.innerHTML = '<div class="signal-loading">暂无数据</div>';
    return;
  }

  const top = sectors[0];
  const level = signal?.confirmation_level || "none";

  const leader = document.createElement("div");
  leader.className = `mainline-leader ${level}`;

  const name = document.createElement("div");
  name.className = "leader-name";
  name.textContent = top.industry;
  leader.append(name);

  const score = document.createElement("span");
  score.className = "leader-score";
  score.innerHTML = `综合评分 ${displayScore(top.score)}`;
  leader.append(score);

  if (signal) {
    const days = document.createElement("span");
    days.className = "leader-days";
    days.textContent = `连续登顶 ${signal.consecutive_days} 天`;
    leader.append(days);

    if (signal.gap != null) {
      const gap = document.createElement("span");
      gap.className = "leader-gap";
      gap.textContent = `领先第二 ${signal.gap.toFixed(3)}`;
      leader.append(gap);
    }
  }

  els.mainlineCurrent.append(leader);
  els.mainlineMeta.textContent = `评分 ${top.score.toFixed(3)}`;
}

function showMainlineIndustryStocks(industry, date = state.selectedDate) {
  const targetIndustry = normalizeIndustry(industry);
  const sector = (state.mainlineData?.sectors || []).find((item) => normalizeIndustry(item.industry) === targetIndustry);
  const rows = Array.isArray(sector?.stocks) ? sector.stocks : [];
  const columns = ["trade_date", "ts_code", "name", "industry", "close", "pct_chg", "amount"];

  state.stockListSource = "mainline";
  state.mode = "industry";
  state.selectedIndustry = targetIndustry;
  state.columns = columns;
  state.rows = rows;
  els.searchInput.value = "";
  els.industryBack.hidden = false;
  els.industryBack.textContent = "← 返回主线";
  syncTabPanels();
  els.industryPanel.hidden = true;
  els.predictionToolbar.hidden = true;
  els.detailPanel.hidden = true;
  els.listPanel.hidden = false;
  els.modeLabel.textContent = "主线行业";
  els.summaryTitle.textContent = targetIndustry;
  els.summaryMeta.textContent = `${displayDate(date)} · ${rows.length} 只股票 · 按成交额排序`;
  els.subtitle.textContent = `主线行业 · ${displayDate(date)} · ${targetIndustry}`;
  els.emptyState.hidden = rows.length > 0;
  els.emptyState.textContent = `${displayDate(date)} 没有行业为 ${targetIndustry} 的主线股票数据`;
  renderDateTabs();
  renderTable(columns, rows);
  renderMobile(columns, rows);
}

async function openMainlineIndustryStocks(industry) {
  const date = state.mainlineData?.date || state.selectedDate || state.latestDate;
  state.activeTab = "mainline";
  document.querySelectorAll(".view-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === "mainline");
  });
  showMainlineIndustryStocks(industry, date);
  els.summaryTitle.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderMainlineTable(sectors) {
  els.mainlineTableBody.innerHTML = "";
  if (!sectors || !sectors.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 8;
    td.textContent = "暂无数据";
    td.style.textAlign = "center";
    td.style.color = "var(--muted)";
    td.style.padding = "20px";
    tr.append(td);
    els.mainlineTableBody.append(tr);
    return;
  }

  for (const s of sectors) {
    const tr = document.createElement("tr");
    if (s.rank === 1) tr.className = "row-top1";
    else if (s.rank <= 3) tr.className = "row-top2";
    tr.title = `查看 ${displayDate(state.selectedDate)} ${s.industry} 股票列表`;
    tr.addEventListener("click", () => openMainlineIndustryStocks(s.industry));

    const rankCell = document.createElement("td");
    const rankBadge = document.createElement("span");
    rankBadge.className = `rank-num rank-${s.rank <= 3 ? s.rank : "other"}`;
    rankBadge.textContent = s.rank;
    rankCell.append(rankBadge);

    const nameCell = document.createElement("td");
    const nameButton = document.createElement("button");
    nameButton.type = "button";
    nameButton.className = "mainline-industry-button";
    nameButton.textContent = s.industry;
    nameButton.title = `查看 ${s.industry} 股票列表`;
    nameCell.append(nameButton);
    nameCell.style.fontWeight = s.rank === 1 ? "800" : "";

    const scoreCell = document.createElement("td");
    scoreCell.className = "score-cell";
    scoreCell.innerHTML = displayScore(s.score);

    const ret5Cell = document.createElement("td");
    ret5Cell.innerHTML = displayReturn(s.return_5d);

    const amtCell = document.createElement("td");
    amtCell.textContent = s.turnover_billion != null ? s.turnover_billion.toFixed(1) : "--";

    const breadthCell = document.createElement("td");
    breadthCell.innerHTML = s.breadth_pct != null ? displayReturn(s.breadth_pct) : "--";

    const nhCell = document.createElement("td");
    nhCell.innerHTML = s.new_high_pct != null ? displayReturn(s.new_high_pct) : "--";

    const rsCell = document.createElement("td");
    rsCell.innerHTML = s.relative_strength != null ? displayReturn(s.relative_strength, "pp") : "--";

    tr.append(rankCell, nameCell, scoreCell, ret5Cell, amtCell, breadthCell, nhCell, rsCell);
    els.mainlineTableBody.append(tr);
  }
}

function renderConceptTable(concepts, emptyMessage = "暂无数据") {
  els.conceptTableBody.innerHTML = "";
  if (!concepts || !concepts.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.className = "concept-empty";
    td.textContent = emptyMessage;
    tr.append(td);
    els.conceptTableBody.append(tr);
    return;
  }

  for (const concept of concepts) {
    const tr = document.createElement("tr");
    if (concept.rank === 1) tr.className = "row-top1";
    else if (concept.rank <= 3) tr.className = "row-top2";
    const stocks = Array.isArray(concept.stocks) ? concept.stocks : [];
    if (stocks.length) {
      tr.title = `查看 ${concept.concept_name} 成分股列表`;
      tr.addEventListener("click", () => openConceptStocks(concept));
    } else {
      tr.classList.add("concept-row-disabled");
      tr.title = "当前日期暂无成分股数据";
    }

    const rankCell = document.createElement("td");
    const rankBadge = document.createElement("span");
    rankBadge.className = `rank-num rank-${concept.rank <= 3 ? concept.rank : "other"}`;
    rankBadge.textContent = concept.rank;
    rankCell.append(rankBadge);

    const nameCell = document.createElement("td");
    nameCell.className = "concept-name";
    const nameButton = document.createElement("button");
    nameButton.type = "button";
    nameButton.className = "mainline-industry-button";
    nameButton.textContent = concept.concept_name;
    nameButton.disabled = stocks.length === 0;
    nameButton.title = stocks.length
      ? `查看 ${concept.concept_name} 的 ${stocks.length} 只成分股`
      : "当前日期暂无成分股数据";
    nameCell.append(nameButton);

    const changeCell = document.createElement("td");
    changeCell.innerHTML = displayReturn(concept.pct_chg);

    const limitUpCell = document.createElement("td");
    limitUpCell.className = "concept-limit-up-count";
    limitUpCell.textContent = Number.isInteger(concept.limit_up_count)
      ? concept.limit_up_count
      : "--";

    const flowCell = document.createElement("td");
    flowCell.innerHTML = displayReturn(concept.net_inflow_billion, "亿");

    const breadthCell = document.createElement("td");
    breadthCell.innerHTML = displayReturn(concept.breadth_pct);

    tr.append(rankCell, nameCell, changeCell, limitUpCell, flowCell, breadthCell);
    els.conceptTableBody.append(tr);
  }
}

function buildFocusStocks(concepts) {
  const stockMap = new Map();

  for (const concept of concepts || []) {
    const conceptName = String(concept.concept_name || "").trim();
    for (const stock of concept.stocks || []) {
      const tsCode = String(stock.ts_code || "").trim().toUpperCase();
      if (!tsCode || !conceptName) continue;

      let item = stockMap.get(tsCode);
      if (!item) {
        item = { ...stock, ts_code: tsCode, concept_names: [] };
        stockMap.set(tsCode, item);
      }
      if (!item.concept_names.includes(conceptName)) {
        item.concept_names.push(conceptName);
      }
    }
  }

  const valueForSort = (value) => {
    const number = Number(value);
    return Number.isFinite(number) ? number : Number.NEGATIVE_INFINITY;
  };

  return [...stockMap.values()]
    .filter((stock) => stock.concept_names.length >= 2)
    .sort((left, right) => (
      right.concept_names.length - left.concept_names.length
      || valueForSort(right.pct_chg) - valueForSort(left.pct_chg)
      || valueForSort(right.amount) - valueForSort(left.amount)
      || left.ts_code.localeCompare(right.ts_code)
    ))
    .map((stock, index) => ({
      ...stock,
      concept_count: stock.concept_names.length,
      focus_rank: index + 1,
    }));
}

function openFocusStockDetail(stock) {
  const date = state.conceptData?.date || state.selectedDate || state.latestDate;
  state.activeTab = "mainline";
  state.stockListSource = "mainline";
  state.mode = "focus-stocks";
  document.querySelectorAll(".view-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === "mainline");
  });
  els.industryBack.hidden = true;
  els.modeLabel.textContent = "重点股票";
  els.summaryTitle.textContent = stock.name || stock.ts_code;
  els.summaryMeta.textContent = `${displayDate(date)} · 命中 ${stock.concept_count} 个概念`;
  els.subtitle.textContent = `重点股票 · ${displayDate(date)} · ${stock.name || stock.ts_code}`;
  showStockDetail(stock.ts_code, stock.name, { returnTarget: "focus-stocks" });
}

function renderFocusStockTable(concepts, emptyMessage = "暂无重点股票") {
  const stocks = buildFocusStocks(concepts);
  state.focusStocks = stocks;
  els.focusStockTableBody.innerHTML = "";
  els.focusStockMeta.textContent = stocks.length
    ? `${stocks.length} 只 · 至少命中 2 个榜单概念`
    : emptyMessage;

  if (!stocks.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.className = "concept-empty";
    td.textContent = emptyMessage;
    tr.append(td);
    els.focusStockTableBody.append(tr);
    return;
  }

  for (const stock of stocks) {
    const tr = document.createElement("tr");
    tr.title = `查看 ${stock.name || stock.ts_code} 日线详情`;
    tr.addEventListener("click", () => openFocusStockDetail(stock));

    const rankCell = document.createElement("td");
    const rankBadge = document.createElement("span");
    rankBadge.className = `rank-num rank-${stock.focus_rank <= 3 ? stock.focus_rank : "other"}`;
    rankBadge.textContent = stock.focus_rank;
    rankCell.append(rankBadge);

    const nameCell = document.createElement("td");
    nameCell.className = "focus-stock-name";
    const nameButton = document.createElement("button");
    nameButton.type = "button";
    nameButton.className = "mainline-industry-button";
    nameButton.textContent = stock.name || stock.ts_code;
    nameButton.title = `查看 ${stock.name || stock.ts_code} 日线详情`;
    nameCell.append(nameButton);

    const codeCell = document.createElement("td");
    codeCell.textContent = stock.ts_code;

    const countCell = document.createElement("td");
    const countBadge = document.createElement("span");
    countBadge.className = "focus-concept-count";
    countBadge.textContent = stock.concept_count;
    countCell.append(countBadge);

    const conceptsCell = document.createElement("td");
    conceptsCell.className = "focus-concepts";
    conceptsCell.textContent = stock.concept_names.join(" · ");
    conceptsCell.title = stock.concept_names.join("、");

    const changeCell = document.createElement("td");
    changeCell.innerHTML = displayReturn(stock.pct_chg);

    tr.append(rankCell, nameCell, codeCell, countCell, conceptsCell, changeCell);
    els.focusStockTableBody.append(tr);
  }
}

function showConceptStocks(concept, date = state.selectedDate) {
  const conceptName = concept.concept_name || "概念板块";
  const rows = Array.isArray(concept.stocks) ? concept.stocks : [];
  const columns = ["trade_date", "ts_code", "name", "industry", "close", "pct_chg", "amount"];

  state.stockListSource = "mainline";
  state.mode = "concept";
  state.selectedIndustry = conceptName;
  state.columns = columns;
  state.rows = rows;
  els.searchInput.value = "";
  els.industryBack.hidden = false;
  els.industryBack.textContent = "← 返回概念榜";
  syncTabPanels();
  els.industryPanel.hidden = true;
  els.predictionToolbar.hidden = true;
  els.detailPanel.hidden = true;
  els.listPanel.hidden = false;
  els.modeLabel.textContent = "概念板块";
  els.summaryTitle.textContent = conceptName;
  els.summaryMeta.textContent = `${displayDate(date)} · ${rows.length} 只股票 · 点击股票进入详情`;
  els.subtitle.textContent = `概念板块 · ${displayDate(date)} · ${conceptName}`;
  els.emptyState.hidden = rows.length > 0;
  els.emptyState.textContent = `${displayDate(date)} 暂无 ${conceptName} 成分股数据`;
  renderDateTabs();
  renderTable(columns, rows);
  renderMobile(columns, rows);
}

function openConceptStocks(concept) {
  const date = state.conceptData?.date || state.selectedDate || state.latestDate;
  state.activeTab = "mainline";
  document.querySelectorAll(".view-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === "mainline");
  });
  showConceptStocks(concept, date);
  els.summaryTitle.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadConceptRanking(date) {
  els.conceptSubtitle.textContent = "加载中";
  try {
    const conceptIndex = state.manifest?.concept_index || {};
    const availableDates = Object.keys(conceptIndex).sort();
    let data = null;
    let dataDate = null;

    if (date) {
      const priorDates = availableDates.filter((availableDate) => availableDate <= date);
      dataDate = conceptIndex[date] ? date : priorDates[priorDates.length - 1] || null;
      if (!dataDate) {
        const firstDate = availableDates[0];
        const message = firstDate
          ? `概念历史从 ${displayDate(firstDate)} 开始`
          : "暂无概念板块数据";
        els.conceptSubtitle.textContent = message;
        renderConceptTable([], message);
        renderFocusStockTable([], message);
        return;
      }
      data = await fetchJson(conceptIndex[dataDate]);
    } else {
      const latestPath = state.manifest?.concept_ranking;
      if (latestPath) data = await fetchJson(latestPath);
    }

    if (!data || !Array.isArray(data.concepts)) {
      throw new Error("暂无概念板块数据");
    }
    if (date !== state.selectedDate) return;

    state.conceptData = data;
    const actualDate = data.date || dataDate;
    els.conceptSubtitle.textContent = actualDate !== date
      ? `${displayDate(actualDate)}（当前日期沿用最近数据）`
      : `${displayDate(actualDate)} · 数据源 ${data.source || "--"}`;
    renderConceptTable(data.concepts);
    renderFocusStockTable(data.concepts);
  } catch (error) {
    if (date !== state.selectedDate) return;
    els.conceptSubtitle.textContent = "读取失败";
    renderConceptTable([], error.message || "读取失败");
    renderFocusStockTable([], error.message || "读取失败");
  }
}

async function loadMainLine(date) {
  loadConceptRanking(date);
  try {
    let data;
    let triedApi = false;

    // When running on h5_server.py, use the API for per-date queries.
    // On GitHub Pages (file:// or no API), fall back to static JSON.
    if (date && (window.location.protocol !== "file:")) {
      triedApi = true;
      try {
        const apiUrl = `/api/mainline?date=${date}&_=${Date.now()}`;
        data = await fetchJson(apiUrl);
      } catch {
        // API not available — fall back to static file
        data = null;
      }
    }

    if (!data && date) {
      const mainlineIndex = state.manifest?.mainline_index || {};
      const staticPath = mainlineIndex[date] || `data/mainline/${date}.json`;
      try {
        data = await fetchJson(staticPath);
      } catch {
        data = null;
      }
    }

    if (!data) {
      const latestPath = state.manifest?.mainline || "data/main_line.json";
      try {
        data = await fetchJson(latestPath);
        if (data && date && data.date !== date) {
          data.requested_date = date;
          data.is_fallback_date = true;
        }
      } catch {
        data = null;
      }
    }

    if (!data || !Array.isArray(data.sectors)) {
      throw new Error("数据格式异常");
    }
    displayMainLineBadge(data.signal?.confirmation_level || data.clarity || "none");
    const dateStr = data.date || "";
    const requestedDate = data.requested_date || date;
    const subtitle = dateStr ? `${dateStr.slice(0,4)}-${dateStr.slice(4,6)}-${dateStr.slice(6,8)}` : "--";
    els.mainlineSubtitle.textContent = data.is_fallback_date && requestedDate
      ? `${subtitle}（${displayDate(requestedDate)}无主线数据，显示最近可用）`
      : subtitle;
    state.mainlineData = data;
    renderSignalCard(data.signal);
    renderCurrentMainline(data.sectors, data.signal);
    renderMainlineTable(data.sectors);
  } catch (error) {
    els.mainlineSubtitle.textContent = "加载失败";
    els.mainlineBadge.textContent = "×";
    els.mainlineBadge.className = "mainline-badge signal-none";
    els.signalCard.innerHTML = `<div class="signal-loading">${error.message}</div>`;
    els.mainlineCurrent.innerHTML = `<div class="signal-loading">${error.message}</div>`;
  }
}

/* ── Strategy Decision Dashboard ── */

function strategyMetricValue(value, suffix = "") {
  if (value == null || Number.isNaN(Number(value))) return "--";
  const number = Number(value);
  const sign = number > 0 && suffix === "%" ? "+" : "";
  return `${sign}${number.toFixed(suffix === "%" ? 2 : 0)}${suffix}`;
}

function renderStrategyCards(strategies) {
  els.strategyCards.innerHTML = "";
  for (const strategy of strategies) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `strategy-card status-${strategy.status}`;
    button.classList.toggle("active", strategy.id === state.activeStrategyId);
    button.setAttribute("aria-pressed", String(strategy.id === state.activeStrategyId));
    button.addEventListener("click", () => {
      state.activeStrategyId = strategy.id;
      renderStrategyCards(strategies);
      renderStrategyDetail(strategy);
    });

    const head = document.createElement("div");
    head.className = "strategy-card-head";
    const name = document.createElement("strong");
    name.textContent = strategy.short_name || strategy.name;
    const status = document.createElement("span");
    status.className = `strategy-status status-${strategy.status}`;
    status.textContent = strategy.status_label || strategy.status;
    head.append(name, status);

    const thesis = document.createElement("p");
    thesis.textContent = strategy.thesis || "--";

    const metrics = document.createElement("div");
    metrics.className = "strategy-card-metrics";
    const walkForwardMetrics = strategy.walk_forward?.metrics || {};
    const metricRows = [
      ["净单笔", strategyMetricValue(strategy.metrics?.net_mean_return_pct, "%")],
      ["基准超额", strategyMetricValue(strategy.metrics?.excess_return_pct, "%")],
      ["滚动回撤", strategyMetricValue(walkForwardMetrics.max_drawdown_pct, "%")],
    ];
    for (const [label, value] of metricRows) {
      const item = document.createElement("span");
      const labelNode = document.createElement("small");
      labelNode.textContent = label;
      const valueNode = document.createElement("b");
      valueNode.textContent = value;
      item.append(labelNode, valueNode);
      metrics.append(item);
    }
    button.append(head, thesis, metrics);
    els.strategyCards.append(button);
  }
}

function renderStrategyMetrics(strategy) {
  const metrics = strategy.metrics || {};
  const walkForward = strategy.walk_forward?.metrics || {};
  els.strategyMetrics.innerHTML = "";
  const items = [
    ["滚动最大回撤", strategyMetricValue(walkForward.max_drawdown_pct, "%"), "样本外逐日净值"],
    ["滚动总收益", strategyMetricValue(walkForward.total_return_pct, "%"), `净值 ${walkForward.latest_nav ?? "--"}`],
    ["启用窗口", `${walkForward.enabled_windows ?? 0}/${walkForward.total_windows ?? 0}`, walkForward.latest_approved ? "最近窗口通过" : "最近窗口未通过"],
    ["样本外信号", walkForward.oos_signal_count == null ? "--" : Number(walkForward.oos_signal_count).toLocaleString("zh-CN"), "仅统计门控通过窗口"],
    ["全量净单笔", strategyMetricValue(metrics.net_mean_return_pct, "%"), "仅作训练参考"],
    ["全量基准超额", strategyMetricValue(metrics.excess_return_pct, "%"), "仅作训练参考"],
  ];
  for (const [label, value, note] of items) {
    const card = document.createElement("div");
    card.className = "strategy-metric";
    const labelNode = document.createElement("span");
    labelNode.textContent = label;
    const valueNode = document.createElement("strong");
    valueNode.textContent = value;
    const noteNode = document.createElement("small");
    noteNode.textContent = note;
    card.append(labelNode, valueNode, noteNode);
    els.strategyMetrics.append(card);
  }
}

function renderStrategyCurve(strategy) {
  const useWalkForward = state.strategyCurveMode === "walk_forward";
  const walkForward = strategy.walk_forward || {};
  const points = useWalkForward
    ? (Array.isArray(walkForward.curve) ? walkForward.curve : [])
    : (Array.isArray(strategy.curve) ? strategy.curve : []);
  const curveMetrics = useWalkForward ? (walkForward.metrics || {}) : (strategy.metrics || {});
  els.strategyWalkForwardMode.classList.toggle("active", useWalkForward);
  els.strategyFullSampleMode.classList.toggle("active", !useWalkForward);
  els.strategyWalkForwardMode.setAttribute("aria-pressed", String(useWalkForward));
  els.strategyFullSampleMode.setAttribute("aria-pressed", String(!useWalkForward));
  els.strategyCurve.innerHTML = "";
  els.strategyCurveMethod.textContent = useWalkForward
    ? (walkForward.curve_method || "暂无滚动回测说明")
    : (strategy.curve_method || "--");
  if (points.length < 2) {
    const empty = svgNode("text", { x: 380, y: 150, "text-anchor": "middle", class: "strategy-chart-label" });
    empty.textContent = "历史数据不足";
    els.strategyCurve.append(empty);
    els.strategyCurveMeta.textContent = "暂无曲线";
    return;
  }

  const width = 760;
  const left = 48;
  const right = 16;
  const navTop = 18;
  const navBottom = 200;
  const drawdownTop = 226;
  const drawdownBottom = 274;
  const plotWidth = width - left - right;
  const navValues = points.map((point) => Number(point.nav)).filter(Number.isFinite);
  const drawdownValues = points.map((point) => Number(point.drawdown_pct)).filter(Number.isFinite);
  let navMin = Math.min(...navValues);
  let navMax = Math.max(...navValues);
  if (navMin === navMax) {
    navMin *= 0.98;
    navMax *= 1.02;
  }
  const drawdownMin = Math.min(...drawdownValues, -0.01);
  const xFor = (index) => left + (index / (points.length - 1)) * plotWidth;
  const navY = (value) => navBottom - ((value - navMin) / (navMax - navMin)) * (navBottom - navTop);
  const drawdownY = (value) => drawdownTop + (value / drawdownMin) * (drawdownBottom - drawdownTop);

  for (const y of [navTop, (navTop + navBottom) / 2, navBottom, drawdownTop, drawdownBottom]) {
    els.strategyCurve.append(svgNode("line", { x1: left, y1: y, x2: width - right, y2: y, class: "strategy-chart-grid" }));
  }

  const drawdownPolygon = [
    `${left},${drawdownTop}`,
    ...points.map((point, index) => `${xFor(index)},${drawdownY(Number(point.drawdown_pct))}`),
    `${width - right},${drawdownTop}`,
  ].join(" ");
  els.strategyCurve.append(svgNode("polygon", { points: drawdownPolygon, class: "strategy-drawdown-area" }));
  const drawdownLine = points.map((point, index) => `${xFor(index)},${drawdownY(Number(point.drawdown_pct))}`).join(" ");
  els.strategyCurve.append(svgNode("polyline", { points: drawdownLine, class: "strategy-drawdown-line" }));
  const navLine = points.map((point, index) => `${xFor(index)},${navY(Number(point.nav))}`).join(" ");
  els.strategyCurve.append(svgNode("polyline", { points: navLine, class: "strategy-nav-line" }));

  const labels = [
    [left - 6, navTop + 4, navMax.toFixed(2), "end"],
    [left - 6, navBottom, navMin.toFixed(2), "end"],
    [left - 6, drawdownTop + 4, "0%", "end"],
    [left - 6, drawdownBottom, `${drawdownMin.toFixed(1)}%`, "end"],
    [left, 296, displayDate(points[0].date), "start"],
    [width - right, 296, displayDate(points[points.length - 1].date), "end"],
  ];
  for (const [x, y, value, anchor] of labels) {
    const label = svgNode("text", { x, y, "text-anchor": anchor, class: "strategy-chart-label" });
    label.textContent = value;
    els.strategyCurve.append(label);
  }

  const maxDrawdown = curveMetrics.max_drawdown_pct;
  const prefix = useWalkForward ? "样本外" : "全量";
  els.strategyCurveMeta.textContent = `${prefix} ${points.length} 日 · 最大回撤 ${strategyMetricValue(maxDrawdown, "%")}`;
}

function renderStrategyRules(strategy) {
  els.strategyRules.innerHTML = "";
  const title = document.createElement("h4");
  title.textContent = "执行纪律";
  els.strategyRules.append(title);
  const latestWindow = strategy.walk_forward?.latest_window;
  const gateSummary = latestWindow
    ? `${displayDate(latestWindow.training_start)}—${displayDate(latestWindow.training_end)}：净单笔 ${strategyMetricValue(latestWindow.training_net_mean_return_pct, "%")}、超额 ${strategyMetricValue(latestWindow.training_excess_return_pct, "%")}、胜率 ${strategyMetricValue(latestWindow.training_win_rate_pct, "%")}，${latestWindow.approved ? "门控通过" : "门控未通过"}`
    : "滚动训练数据不足";
  const rules = [
    ["滚动", gateSummary],
    ["买入", strategy.signal_rule],
    ["退出", strategy.exit_rule],
    ["仓位", strategy.position_rule],
  ];
  const frozenHoldout = strategy.research_split?.frozen_holdout;
  if (frozenHoldout) {
    rules.splice(1, 0, [
      "冻结留出",
      `${frozenHoldout.cohort_count ?? 0} 个完整组合：净单笔 ${strategyMetricValue(frozenHoldout.net_mean_return_pct, "%")}、净值 ${frozenHoldout.latest_nav ?? "--"}、最大回撤 ${strategyMetricValue(frozenHoldout.max_drawdown_pct, "%")}`,
    ]);
  }
  if (Array.isArray(strategy.known_limitations) && strategy.known_limitations.length) {
    rules.push(["限制", strategy.known_limitations.join("；")]);
  }
  for (const [label, value] of rules) {
    const item = document.createElement("div");
    const labelNode = document.createElement("span");
    labelNode.textContent = label;
    const valueNode = document.createElement("p");
    valueNode.textContent = value || "--";
    item.append(labelNode, valueNode);
    els.strategyRules.append(item);
  }
}

function renderStrategyCredibility(strategy) {
  const credibility = strategy.credibility || {};
  els.strategyCredibilityLevel.textContent = credibility.evidence_label || "数据不足";
  els.strategyCredibilityGrid.innerHTML = "";
  const items = [
    ["回测历史", credibility.history_years == null ? "--" : `${Number(credibility.history_years).toFixed(1)} 年`],
    ["完成交易", credibility.completed_trade_count == null ? "--" : Number(credibility.completed_trade_count).toLocaleString("zh-CN")],
    ["涉及股票", credibility.unique_stock_count == null ? "--" : Number(credibility.unique_stock_count).toLocaleString("zh-CN")],
    ["信号日期", credibility.signal_date_count == null ? "--" : Number(credibility.signal_date_count).toLocaleString("zh-CN")],
    ["样本外交易", credibility.oos_completed_trade_count == null ? "--" : Number(credibility.oos_completed_trade_count).toLocaleString("zh-CN")],
    ["启用窗口", `${credibility.enabled_windows ?? 0}/${credibility.total_windows ?? 0}`],
  ];
  for (const [label, value] of items) {
    const item = document.createElement("div");
    item.className = "strategy-credibility-item";
    const labelNode = document.createElement("span");
    labelNode.textContent = label;
    const valueNode = document.createElement("strong");
    valueNode.textContent = value;
    item.append(labelNode, valueNode);
    els.strategyCredibilityGrid.append(item);
  }
  els.strategyCredibilityNote.textContent = credibility.sample_warning
    || "信号数量不等于独立样本；需结合样本外窗口、市场周期和真实成交约束判断。";
}

function openStrategyStock(strategy, row, strategyCase = null) {
  if (!row?.ts_code) return;
  state.stockListSource = "strategy";
  showStockDetail(row.ts_code, row.name || row.ts_code, {
    returnTarget: "strategy",
    strategyCase: strategyCase ? { ...strategyCase, strategy_name: strategy.name } : null,
  });
}

function renderStrategyRecommendations(strategy) {
  const rows = Array.isArray(strategy.recommendations) ? strategy.recommendations : [];
  const signalLabel = strategy.current_signal_label || "原始信号";
  els.strategyRecommendationTitle.textContent = strategy.recommendation_label || "今日候选";
  els.strategyRecommendationNote.textContent = strategy.recommendation_note || "--";
  els.strategyRecommendationCount.textContent = `${rows.length} 只 · ${signalLabel} ${Number(strategy.current_signal_count || 0).toLocaleString("zh-CN")} 只`;
  els.strategyRecommendationBody.innerHTML = "";
  els.strategyTableWrap.hidden = rows.length === 0;
  els.strategyRecommendationEmpty.hidden = rows.length > 0;
  els.strategyRecommendationEmpty.textContent = strategy.recommendation_note || "当前没有符合门槛的股票";

  for (const row of rows) {
    const tr = document.createElement("tr");
    const values = [
      row.rank,
      null,
      null,
      row.industry || "--",
      row.close == null ? "--" : Number(row.close).toFixed(2),
      row.pct_chg == null ? "--" : `${Number(row.pct_chg) > 0 ? "+" : ""}${Number(row.pct_chg).toFixed(2)}%`,
      row.amount_billion == null ? "--" : `${Number(row.amount_billion).toFixed(1)} 亿`,
      (row.reasons || []).join(" · "),
    ];
    values.forEach((value, index) => {
      const td = document.createElement("td");
      if (index === 1) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "strategy-stock-button";
        button.title = `查看 ${row.name || row.ts_code} 日线`;
        button.addEventListener("click", () => openStrategyStock(strategy, row));
        const name = document.createElement("strong");
        name.textContent = row.name || row.ts_code;
        const code = document.createElement("small");
        code.textContent = row.ts_code || "--";
        td.className = "strategy-stock-cell";
        button.append(name, code);
        td.append(button);
      } else if (index === 2) {
        const action = document.createElement("span");
        action.className = `strategy-action ${strategy.status === "active" ? "action-buy" : "action-watch"}`;
        action.textContent = row.action || (strategy.status === "active" ? "候选买入" : "仅观察");
        action.title = row.trigger || "";
        td.append(action);
      } else {
        td.textContent = String(value ?? "--");
      }
      if (index === 5) td.className = Number(row.pct_chg) >= 0 ? "return-up" : "return-down";
      if (index === 7) td.className = "strategy-reasons-cell";
      tr.append(td);
    });
    els.strategyRecommendationBody.append(tr);
  }
}

function renderStrategyHistory(strategy) {
  const history = strategy.historical_cases || {};
  const wins = Array.isArray(history.wins) ? history.wins : [];
  const losses = Array.isArray(history.losses) ? history.losses : [];
  const rows = [...wins, ...losses].sort((a, b) =>
    String(b.signal_date || "").localeCompare(String(a.signal_date || ""))
    || String(a.ts_code || "").localeCompare(String(b.ts_code || ""))
  );
  els.strategyHistoryBody.innerHTML = "";
  els.strategyHistoryTableWrap.hidden = rows.length === 0;
  els.strategyHistoryEmpty.hidden = rows.length > 0;
  els.strategyHistoryNote.textContent = history.definition
    || "最近已完成的盈利与亏损交易，点击股票查看日线。";
  els.strategyHistoryCount.textContent = `盈利 ${history.win_count ?? wins.length} · 亏损 ${history.loss_count ?? losses.length}`;

  for (const row of rows) {
    const tr = document.createElement("tr");
    const outcomeCell = document.createElement("td");
    const outcome = document.createElement("span");
    outcome.className = `strategy-case-outcome ${row.outcome === "win" ? "case-win" : "case-loss"}`;
    outcome.textContent = row.outcome_label || (row.outcome === "win" ? "盈利" : "亏损");
    outcomeCell.append(outcome);

    const scopeCell = document.createElement("td");
    const scope = document.createElement("span");
    scope.className = `strategy-case-scope ${row.evidence_scope === "rolling_oos" ? "scope-oos" : "scope-full"}`;
    scope.textContent = row.evidence_label || "全样本参考";
    scopeCell.append(scope);

    const stockCell = document.createElement("td");
    stockCell.className = "strategy-stock-cell";
    const stockButton = document.createElement("button");
    stockButton.type = "button";
    stockButton.className = "strategy-stock-button";
    stockButton.title = `查看 ${row.name || row.ts_code} 日线与案例位置`;
    stockButton.addEventListener("click", () => openStrategyStock(strategy, row, row));
    const name = document.createElement("strong");
    name.textContent = row.name || row.ts_code;
    const code = document.createElement("small");
    code.textContent = row.ts_code || "--";
    stockButton.append(name, code);
    stockCell.append(stockButton);

    const signalDate = document.createElement("td");
    signalDate.textContent = displayDate(row.signal_date);
    const entryDate = document.createElement("td");
    entryDate.textContent = displayDate(row.entry_date);
    const exitDate = document.createElement("td");
    exitDate.textContent = displayDate(row.exit_date);
    const returnCell = document.createElement("td");
    returnCell.className = Number(row.net_return_pct) >= 0 ? "return-up" : "return-down";
    returnCell.textContent = strategyMetricValue(row.net_return_pct, "%");
    const exitReason = document.createElement("td");
    exitReason.textContent = row.exit_reason || "--";
    const reasons = document.createElement("td");
    reasons.className = "strategy-reasons-cell";
    reasons.textContent = (row.reasons || []).join(" · ");
    tr.append(outcomeCell, scopeCell, stockCell, signalDate, entryDate, exitDate, returnCell, exitReason, reasons);
    els.strategyHistoryBody.append(tr);
  }
}

function renderStrategyDetail(strategy) {
  els.strategyDetail.hidden = false;
  els.strategyError.hidden = true;
  els.strategyDetailTitle.textContent = strategy.name || "--";
  els.strategyDetailStatus.textContent = `${strategy.status_label || strategy.status} · 置信度 ${strategy.confidence || "--"}`;
  els.strategyDetailStatus.className = `strategy-status status-${strategy.status}`;
  els.strategyThesis.textContent = strategy.thesis || "--";
  els.strategyEvidence.textContent = strategy.evidence || "--";
  renderStrategyMetrics(strategy);
  renderStrategyCredibility(strategy);
  renderStrategyCurve(strategy);
  renderStrategyRules(strategy);
  renderStrategyRecommendations(strategy);
  renderStrategyHistory(strategy);
}

function renderStrategies(payload) {
  const strategies = Array.isArray(payload.strategies) ? payload.strategies : [];
  if (!strategies.length) throw new Error("暂无策略回测数据");
  state.strategyData = payload;
  if (!state.activeStrategyId || !strategies.some((item) => item.id === state.activeStrategyId)) {
    state.activeStrategyId = strategies.find((item) => item.status === "active")?.id || strategies[0].id;
  }
  els.strategySubtitle.textContent = `${strategies.length} 个策略 · ${payload.summary?.active_strategy_count || 0} 个条件执行 · ${payload.summary?.active_recommendation_count || 0} 只候选`;
  els.strategyAsOf.textContent = `数据截至 ${displayDate(payload.as_of_date)}`;
  els.strategyRiskNotice.textContent = payload.risk_notice || els.strategyRiskNotice.textContent;
  renderStrategyCards(strategies);
  renderStrategyDetail(strategies.find((item) => item.id === state.activeStrategyId) || strategies[0]);
}

async function loadStrategies() {
  els.strategyError.hidden = true;
  if (state.strategyData) {
    renderStrategies(state.strategyData);
    return;
  }
  try {
    const path = state.manifest?.strategies || "data/strategies.json";
    renderStrategies(await fetchJson(path));
  } catch (error) {
    els.strategyCards.innerHTML = "";
    els.strategyDetail.hidden = true;
    els.strategyError.hidden = false;
    els.strategyError.textContent = error.message || "策略数据读取失败";
  }
}

/* ── Tab Switching ── */

function switchTab(tabName, options = {}) {
  const previousStockListSource = state.stockListSource;
  state.activeTab = tabName;
  if (tabName === "b1") {
    state.stockListSource = "b1";
  } else if (tabName === "strategy" && state.stockListSource === "strategy") {
    state.stockListSource = "b1";
    state.detailCase = null;
  }

  // Update tab buttons
  document.querySelectorAll(".view-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tabName);
  });

  // Show/hide tab content
  syncTabPanels();
  els.dateTabs.hidden = tabName === "strategy";

  // Update subtitle
  if (tabName === "mainline") {
    els.subtitle.textContent = `主线监控 · ${displayDate(state.selectedDate)}`;
  } else if (tabName === "b1") {
    els.subtitle.textContent = `B1 信号 · ${displayDate(state.selectedDate)}`;
  } else {
    els.subtitle.textContent = `策略决策 · ${displayDate(state.manifest?.latest_date || state.selectedDate)}`;
  }

  // Reload content for current date
  if (options.skipReload) return;

  if (tabName === "mainline") {
    state.stockListSource = "b1";
    syncTabPanels();
    loadMainLine(state.selectedDate);
  } else if (tabName === "strategy") {
    loadStrategies();
  } else if (state.dateDataDate !== state.selectedDate) {
    loadDate(state.selectedDate);
  } else if (previousStockListSource !== "b1" || state.mode === "industry") {
    renderCachedDateData();
  } else {
    showListView();
    updatePredictionToolbar();
  }
}

/* ── Date selection — tab-aware ── */

async function onDateSelect(date) {
  state.selectedDate = date;
  state.mode = "date";
  state.stockListSource = "b1";
  els.searchInput.value = "";
  renderDateTabs();

  if (state.activeTab === "mainline") {
    els.industryBack.hidden = true;
    els.listPanel.hidden = true;
    els.detailPanel.hidden = true;
    els.industryPanel.hidden = true;
    els.predictionToolbar.hidden = true;
    syncTabPanels();
    els.subtitle.textContent = `主线监控 · ${displayDate(date)}`;
    loadMainLine(date);
  } else {
    syncTabPanels();
    loadDate(date);
  }
}

async function init() {
  state.activeTab = "mainline";
  els.subtitle.textContent = "加载日期";
  try {
    const payload = await fetchJson("data/manifest.json");
    state.manifest = payload;
    
    if (!payload.latest_date || !payload.dates || payload.dates.length === 0) {
      els.subtitle.textContent = "请先生成数据，在项目根目录运行：python export_web_data.py";
      els.emptyState.hidden = false;
      els.emptyState.textContent = "尚未生成数据文件，请运行数据导出命令";
      return;
    }
    
    syncDates(payload);
    state.selectedDate = payload.latest_date;

    // Switch to default tab (mainline)
    switchTab("mainline");

    // Also preload B1 data in background
    Promise.all([
      ensureDateData(payload.latest_date),
      loadIndustryTrends(),
    ]).catch(() => {});
  } catch (error) {
    els.subtitle.textContent = "初始化失败";
  }
}

// Tab click handlers
document.querySelectorAll(".view-tab").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

function setStrategyCurveMode(mode) {
  state.strategyCurveMode = mode === "full_sample" ? "full_sample" : "walk_forward";
  const strategy = state.strategyData?.strategies?.find((item) => item.id === state.activeStrategyId);
  if (strategy) renderStrategyCurve(strategy);
}

els.strategyWalkForwardMode.addEventListener("click", () => setStrategyCurveMode("walk_forward"));
els.strategyFullSampleMode.addEventListener("click", () => setStrategyCurveMode("full_sample"));

els.predictionOnly.addEventListener("click", () => applyListFilter("predictions"));
els.showAllStocks.addEventListener("click", () => applyListFilter("all"));

els.searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = els.searchInput.value.trim();
  if (query) {
    // Switch to B1 tab for search results
    if (state.activeTab !== "b1") switchTab("b1");
    runSearch(query);
  } else if (state.selectedDate) {
    onDateSelect(state.selectedDate);
  }
});

els.clearSearch.addEventListener("click", () => {
  els.searchInput.value = "";
  if (state.selectedDate) {
    onDateSelect(state.selectedDate);
  }
});

// Override date tab clicks — each date button already has a click handler
// in renderDateTabs that calls loadDate(). We'll patch renderDateTabs.
const _origRenderDateTabs = renderDateTabs;
renderDateTabs = function() {
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
    button.className = item.date === state.selectedDate ? "active" : "";
    button.title = (item.files || []).join("\n");
    button.addEventListener("click", () => onDateSelect(item.date));
    els.dateTabs.append(button);
  }
};

init();
