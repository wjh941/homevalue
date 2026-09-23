/* HomeValue 仪表盘:原生 JS + 手写 SVG 图表,无外部依赖 */
"use strict";

const $ = (id) => document.getElementById(id);
const CITY_NAMES = { bj: "北京", sh: "上海", gz: "广州", sz: "深圳", hz: "杭州" };
const fmt = (n, digits = 0) =>
  n == null ? "--" : Number(n).toLocaleString("zh-CN", { maximumFractionDigits: digits });

async function jget(url) {
  const r = await fetch(url);
  if (!r.ok) {
    const body = await r.text();
    throw new Error(url + " -> " + r.status + " " + body.slice(0, 200));
  }
  return r.json();
}

async function jpost(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(text.slice(0, 300));
  }
  return r.json();
}

/* ---------------- SVG 图表(无依赖,悬浮提示) ---------------- */

function svgEl(tag, attrs) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
  return el;
}

function svgTitle(text) {
  const t = svgEl("title", {});
  t.textContent = text;
  return t;
}

// 日期轴:MM-DD 短标签旋转排布(自适应密度),年份分隔线 + 年份行
function drawDateAxis(svg, dates, xs, opts) {
  const width = opts.width, height = opts.height, padL = opts.padL, padR = opts.padR;
  const plotW = width - padL - padR;
  const every = Math.max(1, Math.ceil(dates.length / Math.max(3, Math.floor(plotW / 30))));
  dates.forEach((d, i) => {
    if (i % every !== 0 && i !== dates.length - 1) return;
    const t = svgEl("text", {
      x: xs(i), y: height - 30, "text-anchor": "end",
      transform: "rotate(-35 " + xs(i) + " " + (height - 30) + ")",
    });
    t.textContent = d.slice(5); // MM-DD
    svg.appendChild(t);
  });
  const years = [];
  dates.forEach((d) => {
    const y = d.slice(0, 4);
    if (!years.length || years[years.length - 1].year !== y) years.push({ year: y, start: dates.indexOf(d) });
  });
  years.forEach((yr, k) => {
    const endI = k + 1 < years.length ? years[k + 1].start - 1 : dates.length - 1;
    if (k > 0) {
      svg.appendChild(svgEl("line", {
        x1: xs(yr.start) - 5, x2: xs(yr.start) - 5, y1: 12, y2: height - 44,
        stroke: "#2a3a5f", "stroke-dasharray": "3 3",
      }));
    }
    const t = svgEl("text", {
      x: (xs(yr.start) + xs(endI)) / 2, y: height - 8, "text-anchor": "middle",
      style: "font-size:12px;font-weight:600;fill:#8b9bb8",
    });
    t.textContent = yr.year;
    svg.appendChild(t);
  });
}

function barChart(items, opts = {}) {
  // items: [{label, value}];横向条形图;悬浮显示数值,可选 onBarClick(label)
  if (!items || !items.length) return document.createTextNode("暂无数据");
  const width = opts.width || 480;
  const rowH = 24;
  const padL = 90, padR = 70, padT = 8, padB = 8;
  const height = padT + padB + items.length * rowH;
  const max = Math.max(...items.map((d) => d.value)) || 1;
  const svg = svgEl("svg", { viewBox: "0 0 " + width + " " + height, class: "bar-chart" });
  items.forEach((d, i) => {
    const y = padT + i * rowH;
    const w = Math.max(2, (d.value / max) * (width - padL - padR));
    svg.appendChild(svgEl("text", { x: padL - 8, y: y + 15, "text-anchor": "end", class: "bar-label" })).textContent = d.label;
    const rect = svgEl("rect", {
      x: padL, y: y + 4, width: w, height: 15, rx: 3,
      fill: opts.color || "#4f8cff", "data-label": d.label,
      style: opts.onBarClick ? "cursor:pointer" : "",
    });
    rect.appendChild(svgTitle((opts.tipFormatter || ((dd) => dd.label + ": " + (opts.formatter || fmt)(dd.value)))(d)));
    svg.appendChild(rect);
    const t = svgEl("text", { x: padL + w + 6, y: y + 15, class: "bar-value" });
    t.textContent = (opts.formatter || fmt)(d.value);
    svg.appendChild(t);
  });
  if (opts.onBarClick) {
    svg.addEventListener("click", (e) => {
      const label = e.target && e.target.getAttribute && e.target.getAttribute("data-label");
      if (label) opts.onBarClick(label);
    });
  }
  return svg;
}

function lineChart(points, opts = {}) {
  if (!points || points.length < 2) return document.createTextNode("该年份窗口内快照不足 2 期,切回「全部」查看完整走势");
  const width = opts.width || 520, height = opts.height || 300;
  const padL = 62, padR = 14, padT = 14, padB = 60;
  const vals = points.map((p) => p.value);
  const min = Math.min(...vals) * 0.96, max = Math.max(...vals) * 1.02;
  const xs = (i) => padL + (i / (points.length - 1)) * (width - padL - padR);
  const ys = (v) => padT + (1 - (v - min) / (max - min || 1)) * (height - padT - padB);
  const svg = svgEl("svg", { viewBox: "0 0 " + width + " " + height, class: "line-chart" });
  for (let g = 0; g <= 3; g++) {
    const v = min + ((max - min) * g) / 3;
    svg.appendChild(svgEl("line", { x1: padL, x2: width - padR, y1: ys(v), y2: ys(v), stroke: "#24304f", "stroke-width": 1 }));
    const t = svgEl("text", { x: padL - 6, y: ys(v) + 3, "text-anchor": "end" });
    t.textContent = (v / 10000).toFixed(2) + "万";
    svg.appendChild(t);
  }
  const path = points.map((p, i) => (i ? "L" : "M") + xs(i).toFixed(1) + "," + ys(p.value).toFixed(1)).join(" ");
  svg.appendChild(svgEl("path", { d: path, fill: "none", stroke: "#34d399", "stroke-width": 2 }));
  points.forEach((p, i) => {
    const dot = svgEl("circle", { cx: xs(i), cy: ys(p.value), r: 3.5, fill: "#34d399" });
    dot.appendChild(svgTitle(p.label + " · " + fmt(p.value) + " 元/㎡" + (p.mom != null ? " · 环比 " + p.mom + "%" : "")));
    svg.appendChild(dot);
  });
  drawDateAxis(svg, points.map((p) => p.label), xs, { width, height, padL, padR });
  return svg;
}

// 多序列折线(区对比):series = [{name, color, points:[{label, value}]}]
const PALETTE = ["#34d399", "#4f8cff", "#f59e0b", "#f87171", "#a78bfa", "#22d3ee"];

function multiLineChart(series, opts = {}) {
  const dates = [...new Set(series.flatMap((s) => s.points.map((p) => p.label)))].sort();
  if (dates.length < 2 || !series.length) return document.createTextNode("数据不足");
  const idx = {};
  dates.forEach((d, i) => (idx[d] = i));
  const vals = series.flatMap((s) => s.points.map((p) => p.value));
  const min = Math.min(...vals) * 0.96, max = Math.max(...vals) * 1.02;
  const width = opts.width || 520, height = opts.height || 300;
  const padL = 62, padR = 14, padT = 14, padB = 60;
  const xs = (i) => padL + (i / (dates.length - 1)) * (width - padL - padR);
  const ys = (v) => padT + (1 - (v - min) / (max - min || 1)) * (height - padT - padB);
  const svg = svgEl("svg", { viewBox: "0 0 " + width + " " + height, class: "line-chart" });
  for (let g = 0; g <= 3; g++) {
    const v = min + ((max - min) * g) / 3;
    svg.appendChild(svgEl("line", { x1: padL, x2: width - padR, y1: ys(v), y2: ys(v), stroke: "#24304f", "stroke-width": 1 }));
    const t = svgEl("text", { x: padL - 6, y: ys(v) + 3, "text-anchor": "end" });
    t.textContent = (v / 10000).toFixed(2) + "万";
    svg.appendChild(t);
  }
  drawDateAxis(svg, dates, xs, { width, height, padL, padR });
  series.forEach((s) => {
    const pts = s.points
      .map((p) => ({ i: idx[p.label], v: p.value, label: p.label }))
      .filter((p) => p.i != null)
      .sort((a, b) => a.i - b.i);
    if (pts.length < 2) return;
    const path = pts.map((p, j) => (j ? "L" : "M") + xs(p.i).toFixed(1) + "," + ys(p.v).toFixed(1)).join(" ");
    svg.appendChild(svgEl("path", { d: path, fill: "none", stroke: s.color, "stroke-width": 2 }));
    pts.forEach((p) => {
      const dot = svgEl("circle", { cx: xs(p.i), cy: ys(p.v), r: 3, fill: s.color });
      dot.appendChild(svgTitle(s.name + " · " + p.label + " · " + fmt(p.v) + " 元/㎡"));
      svg.appendChild(dot);
    });
  });
  return svg;
}

// 趋势事实提取(供自动结论)
function trendFacts(points) {
  if (!points || points.length < 2) return [];
  const f = points[0], l = points[points.length - 1];
  const out = [];
  const cum = (((l.value - f.value) / f.value) * 100).toFixed(1);
  out.push("期间累计 " + (cum > 0 ? "+" : "") + cum + "%(" + f.label.slice(2) + " -> " + l.label.slice(2) + ")");
  let hi = points[0], lo = points[0], maxDrop = null, run = 0, maxRun = 0;
  for (let i = 1; i < points.length; i++) {
    const prev = points[i - 1].value, cur = points[i].value;
    const mom = ((cur - prev) / prev) * 100;
    if (mom < 0) { run += 1; maxRun = Math.max(maxRun, run); } else { run = 0; }
    if (!maxDrop || mom < maxDrop.mom) maxDrop = { label: points[i].label, mom: mom };
    if (cur > hi.value) hi = points[i];
    if (cur < lo.value) lo = points[i];
  }
  out.push("最高点 " + hi.label.slice(2) + "(" + fmt(hi.value) + "),最低点 " + lo.label.slice(2) + "(" + fmt(lo.value) + ")");
  if (maxDrop) out.push("单期最大跌幅 " + maxDrop.mom.toFixed(1) + "%(" + maxDrop.label.slice(2) + ")");
  if (maxRun > 0) out.push("最长连续下跌 " + maxRun + " 期");
  return out;
}

/* ---------------- 顶部状态 ---------------- */

async function loadHeader() {
  const health = await jget("/api/health");
  const overview = await jget("/api/analysis/overview");
  const h = health.holdout || {};
  const fr = health.data_freshness || {};
  const chips = [
    ["在售房源", overview.n_listings ? fmt(overview.n_listings) + " 套" : "--"],
    ["留出集 MAE", h.mae != null ? fmt(h.mae) + " 元/㎡" : "--"],
    ["MAPE", h.mape_pct != null ? h.mape_pct + "%" : "--"],
    ["R²", h.r2 != null ? h.r2 : "--"],
    ["数据截至", fr.last_snapshot ? String(fr.last_snapshot).slice(0, 10) : "--"],
    ["数据后端", health.data_backend === "sqlite" ? "SQLite 实时" : "预计算缓存"],
  ];
  $("top-stats").innerHTML = chips.map(([k, v]) => '<div class="chip">' + k + " <b>" + v + "</b></div>").join("");
  const sel = $("f-district");
  (overview.districts_all || []).forEach((d) => {
    const opt = document.createElement("option");
    opt.value = d.district;
    opt.textContent = d.district + "(均价 " + fmt(d.avg_unit_price) + ")";
    sel.appendChild(opt);
  });
}

/* ---------------- 估值 ---------------- */

function gotoPredict(district) {
  const sel = $("f-district");
  for (const o of sel.options) {
    if (o.value === district) {
      sel.value = district;
      break;
    }
  }
  const tab = document.querySelector('[data-view="predict"]');
  if (tab) tab.click();
  document.getElementById("view-predict").scrollIntoView({ behavior: "smooth" });
}

$("predict-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("predict-btn");
  btn.disabled = true;
  btn.textContent = "计算中...";
  $("result-error").classList.add("hidden");
  const payload = {
    district: $("f-district").value,
    bizcircle: $("f-bizcircle").value.trim() || null,
    rooms: Number($("f-rooms").value),
    halls: Number($("f-halls").value),
    area_sqm: Number($("f-area").value),
    build_year: $("f-year").value ? Number($("f-year").value) : null,
    floor_pos: $("f-floor").value,
    total_floors: $("f-total-floors").value ? Number($("f-total-floors").value) : null,
    dir_main: $("f-dir").value,
    renovation: $("f-renovation").value,
  };
  try {
    const res = await jpost("/api/predict", payload);
    renderResult(res);
  } catch (err) {
    $("result-empty").classList.add("hidden");
    const box = $("result-error");
    box.textContent = /Failed to fetch|NetworkError/.test(err.message)
      ? "网络异常或服务正在冷启动(免费实例约 50 秒),请稍后重试。"
      : "估值失败: " + err.message;
    box.classList.remove("hidden");
  } finally {
    btn.disabled = false;
    btn.textContent = "立即估值";
  }
});

function renderResult(res) {
  $("result-empty").classList.add("hidden");
  $("result-body").classList.remove("hidden");
  const p = res.unit_price;
  $("r-price").textContent = fmt(p.p50);
  $("r-p10").textContent = fmt(p.p10);
  $("r-p90").textContent = fmt(p.p90);
  const spanPct = Math.min(100, ((p.p90 - p.p10) / p.p90) * 100 * 2);
  $("r-interval-fill").style.width = spanPct.toFixed(0) + "%";
  $("r-total").textContent = fmt(res.total_price_wan.p50, 1);
  $("r-width").textContent = res.interval_width_pct + "%";
  const comps = res.comparables || {};
  let compHtml = "";
  if (comps.district && typeof comps.district === "object") {
    compHtml = '<div class="comp-block">参照 <b>' + comps.district.district + "</b>:" + fmt(comps.district.n) + " 套在售,均价 " + fmt(comps.district.avg_price) + " 元/㎡</div>";
  } else if (comps.district_avg_price) {
    compHtml = '<div class="comp-block">该区挂牌均价 <b>' + fmt(comps.district_avg_price) + "</b> 元/㎡</div>";
  }
  if (comps.bizcircle) {
    compHtml += '<div class="comp-block">商圈 <b>' + comps.bizcircle.name + "</b>:" + fmt(comps.bizcircle.n) + " 套,均价 " + fmt(comps.bizcircle.avg_price) + " 元/㎡</div>";
  }
  $("r-comps").innerHTML = compHtml;

  const sim = res.similar || [];
  if (sim.length) {
    const rows = sim
      .map(
        (s) =>
          "<tr><td>" + (s.community || "--") + "</td><td>" + fmt(s.area_sqm, 1) + "㎡</td><td>" + fmt(s.unit_price) + "</td><td>" +
          (s.rooms == null ? "--" : s.rooms + "室" + (s.halls || 0) + "厅") + "</td><td>" + (s.build_year || "--") + "</td></tr>"
      )
      .join("");
    $("r-similar").innerHTML =
      '<table class="similar"><thead><tr><th>同区相似在售</th><th>面积</th><th>挂牌单价</th><th>户型</th><th>年代</th></tr></thead><tbody>' +
      rows + '</tbody></table><p class="hint">挂牌价通常高于成交价,仅作参照。</p>';
  } else {
    $("r-similar").innerHTML = "";
  }

  $("r-meta").textContent = "模型 " + res.model_version + " · 目标为单价,总价 = 单价 × 面积";
}

/* ---------------- 市场分析:洞察条 + 全国/城市切换 ---------------- */

const marketState = {
  city: "all", year: "all", overview: null, trendAll: null, districtsAll: null,
  changes: null, districtTrend: null, compare: new Set(["西城", "朝阳", "海淀"]),
};

function kpiCard(v, k, cls) {
  return '<div class="kpi ' + (cls || "") + '"><b>' + v + "</b><span>" + k + "</span></div>";
}

function renderInsights() {
  const { overview, trendAll, changes } = marketState;
  const bjTrend = (trendAll || []).filter((r) => r.city === "bj" && r.n_listings > 5000);
  const first = bjTrend[0], last = bjTrend[bjTrend.length - 1];
  const cumPct = first && last ? (((last.avg_unit_price - first.avg_unit_price) / first.avg_unit_price) * 100).toFixed(1) : null;
  const cc = marketState.cityCompare || [];
  const best = cc.find((c) => c.rank_by_price === 1);
  const s = (changes.summary || [])[0] || {};
  const cards = [
    best ? [CITY_NAMES[best.city] || best.city, "均价最高城市 · " + fmt(best.avg_unit_price) + " 元/㎡"] : null,
    cumPct != null ? ["北京挂牌价两年 " + cumPct + "%", first.snapshot_date.slice(0, 4) + " -> " + last.snapshot_date.slice(0, 4) + " · " + fmt(first.avg_unit_price) + " -> " + fmt(last.avg_unit_price)] : null,
    s.pct_reduced != null ? ["降价房源占 " + s.pct_reduced + "%", "跨快照调价 " + fmt(s.n_changed) + " 套 · 平均 " + s.avg_pct_change + "%"] : null,
    overview.districts_all && overview.districts_all[0]
      ? ["北京最贵区 " + overview.districts_all[0].district, "挂牌均价 " + fmt(overview.districts_all[0].avg_unit_price) + " 元/㎡ · " + fmt(overview.districts_all[0].n_listings) + " 套"]
      : null,
    overview.top20_value_share != null ? ["总价 TOP20% 房源", "占全城挂牌总额 " + overview.top20_value_share + "%(帕累托)"] : null,
  ].filter(Boolean);
  $("insight-strip").innerHTML = cards.map(([v, k]) => kpiCard(v, k, "insight")).join("");
}

function renderCityView() {
  const city = marketState.city;
  const trendAll = marketState.trendAll || [];
  const districtsAll = marketState.districtsAll || [];
  const cc = marketState.cityCompare || [];
  const isAll = city === "all";

  // 城市卡(全国对比时)
  if (isAll) {
    const bj = cc.find((c) => c.city === "bj");
    $("city-cards").innerHTML = cc
      .map((c) => {
        const delta = bj && c.city !== "bj" ? (((c.avg_unit_price - bj.avg_unit_price) / bj.avg_unit_price) * 100).toFixed(1) + "% vs 北京" : "基准";
        return kpiCard(CITY_NAMES[c.city] || c.city, fmt(c.n_listings) + " 套 · 均价 " + fmt(c.avg_unit_price) + " 元/㎡ · " + delta);
      })
      .join("");
    $("trend-title").textContent = "北京挂牌均价走势(35 期快照环比)";
    $("trend-note").textContent = "悬浮数据点可查看当期均价与环比;2024-09 快照为部分抓取,仅供参考。";
  } else {
    const c = cc.find((x) => x.city === city);
    $("city-cards").innerHTML = c
      ? kpiCard(CITY_NAMES[city] || city, fmt(c.n_listings) + " 套 · 均价 " + fmt(c.avg_unit_price) + " 元/㎡ · 五城中按均价第 " + c.rank_by_price + " 位")
      : "";
    $("trend-title").textContent = CITY_NAMES[city] + " 挂牌均价走势";
    $("trend-note").textContent = "悬浮数据点可查看当期均价与环比。";
  }

  // 趋势(年份钻取)
  $("trend-title").textContent = isAll ? "北京挂牌均价走势(35 期快照)" : CITY_NAMES[city] + " 挂牌均价走势";
  renderTrendArea();

  // 区对比(仅北京数据)
  renderDistrictCompare();
  renderConclusions();

  // 区域排名
  const dr = isAll
    ? cc.map((c) => ({ label: CITY_NAMES[c.city] || c.city, value: c.avg_unit_price, city: c.city }))
    : districtsAll
        .filter((r) => r.city === city)
        .map((r) => ({ label: r.district, value: r.avg_unit_price, district: r.district }));
  $("district-title").textContent = isAll ? "五城挂牌均价对比" : CITY_NAMES[city] + " 各区挂牌均价排名";
  $("district-note").textContent = isAll ? "均价为该城全部在售挂牌的平均值。" : "点击条形可一键带入估值表单(模型基于北京数据训练)。";
  $("chart-districts").replaceChildren(
    barChart(dr.slice().reverse(), {
      color: isAll ? "#f59e0b" : "#4f8cff",
      onBarClick: isAll
        ? null
        : (label) => {
            if (city === "bj") gotoPredict(label);
          },
      tipFormatter: (d) => d.label + ": " + fmt(d.value) + " 元/㎡",
    })
  );
}

function renderTrendArea() {
  const city = marketState.city === "all" ? "bj" : marketState.city;
  const year = marketState.year;
  const tp = (marketState.trendAll || [])
    .filter((r) => r.city === city)
    .filter((r) => year === "all" || String(r.snapshot_date).slice(0, 4) === year)
    .map((r) => ({ label: r.snapshot_date, value: r.avg_unit_price }));
  $("chart-trend").replaceChildren(lineChart(tp, { height: 280 }));
}

function renderDistrictCompare() {
  const year = marketState.year;
  const rows = marketState.districtTrend || [];
  const districts = [...new Set(rows.map((r) => r.district))].sort();
  // 区名 chip(默认选中三个,点击切换)
  const box = $("district-switch");
  box.innerHTML = districts
    .map((d) => {
      const active = marketState.compare.has(d);
      const color = active ? PALETTE[districts.indexOf(d) % PALETTE.length] : "transparent";
      return '<button data-d="' + d + '" class="' + (active ? "active" : "") +
        '" style="' + (active ? "border-color:" + color + ";color:" + color : "") + '">' + d + "</button>";
    })
    .join("");
  box.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const d = btn.dataset.d;
      if (marketState.compare.has(d)) marketState.compare.delete(d);
      else if (marketState.compare.size < 5) marketState.compare.add(d);
      renderDistrictCompare();
      renderConclusions();
    });
  });

  const series = [...marketState.compare].map((d, i) => ({
    name: d,
    color: PALETTE[districts.indexOf(d) % PALETTE.length],
    points: rows
      .filter((r) => r.district === d)
      .filter((r) => year === "all" || String(r.snapshot_date).slice(0, 4) === year)
      .map((r) => ({ label: r.snapshot_date, value: r.avg_unit_price })),
  }));
  $("chart-district-trend").replaceChildren(multiLineChart(series, { height: 280 }));
}

function renderConclusions() {
  const city = marketState.city === "all" ? "bj" : marketState.city;
  const year = marketState.year;
  const tp = (marketState.trendAll || [])
    .filter((r) => r.city === city)
    .filter((r) => year === "all" || String(r.snapshot_date).slice(0, 4) === year)
    .map((r) => ({ label: r.snapshot_date, value: r.avg_unit_price }));

  const items = [];
  const cityName = marketState.city === "all" ? "北京" : CITY_NAMES[marketState.city];
  trendFacts(tp).forEach((s) => items.push(cityName + "全市:" + s));

  const rows = marketState.districtTrend || [];
  const stats = [...marketState.compare]
    .map((d) => {
      const pts = rows
        .filter((r) => r.district === d)
        .filter((r) => year === "all" || String(r.snapshot_date).slice(0, 4) === year)
        .sort((a, b) => (a.snapshot_date < b.snapshot_date ? -1 : 1));
      if (pts.length < 2) return null;
      const first = pts[0].avg_unit_price, last = pts[pts.length - 1].avg_unit_price;
      return { district: d, pct: ((last - first) / first) * 100, last };
    })
    .filter(Boolean)
    .sort((a, b) => a.pct - b.pct);
  if (stats.length >= 2) {
    items.push("对比期内最抗跌:" + stats[stats.length - 1].district + "(" + (stats[stats.length - 1].pct > 0 ? "+" : "") + stats[stats.length - 1].pct.toFixed(1) + "%),跌幅最大:" + stats[0].district + "(" + stats[0].pct.toFixed(1) + "%)");
    const spread = (stats[stats.length - 1].pct - stats[0].pct).toFixed(1);
    items.push("区间分化 " + spread + " 个百分点:同期不同区走势差异显著,估值须看区不看城");
  } else if (stats.length === 1) {
    items.push(stats[0].district + ":" + (stats[0].pct > 0 ? "+" : "") + stats[0].pct.toFixed(1) + "%");
  }
  if (year !== "all") items.push("当前窗口:" + year + " 年(快照为不定期抓取,无日内粒度)");

  $("conclusion-list").innerHTML = items.map((s) => "<li>" + s + "</li>").join("");
}

function buildDistrictSwitch() {
  // 首次渲染由 renderDistrictCompare 生成;此函数仅占位保持加载顺序清晰
}

async function loadMarket() {
  const [overview, trend, deciles, changes, trendAll, districtsAll, districtTrend] = await Promise.all([
    jget("/api/analysis/overview"),
    jget("/api/analysis/trend"),
    jget("/api/analysis/deciles"),
    jget("/api/analysis/price-changes"),
    jget("/api/analysis/trend-all"),
    jget("/api/analysis/districts-all"),
    jget("/api/analysis/district-trend"),
  ]);
  Object.assign(marketState, { overview, trend, deciles, changes, trendAll, districtsAll, districtTrend });
  marketState.cityCompare = changes.city_compare || [];

  buildDistrictSwitch();
  renderInsights();
  renderCityView();

  $("table-deciles").innerHTML =
    '<table><thead><tr><th>分位</th><th>区间(元/㎡)</th><th>均价</th><th>平均面积</th><th>套数</th></tr></thead><tbody>' +
    deciles
      .map(
        (r) =>
          "<tr><td>D" + r.decile + "</td><td>" + fmt(r.price_min) + " ~ " + fmt(r.price_max) + "</td><td>" + fmt(r.avg_unit_price) + "</td><td>" + r.avg_area + "㎡</td><td>" + fmt(r.n_listings) + "</td></tr>"
      )
      .join("") +
    "</tbody></table>";

  const s = (changes.summary || [])[0];
  const cc = changes.city_compare || [];
  $("price-changes").innerHTML =
    '<div class="comp-block">跨快照同房源调价 <b>' + fmt(s && s.n_changed) + "</b> 套,平均变动 <b>" +
    ((s && s.avg_pct_change) ?? "--") + "%</b>,降价占比 <b>" + ((s && s.pct_reduced) ?? "--") + "%</b></div>" +
    '<table style="margin-top:10px"><thead><tr><th>城市</th><th>套数</th><th>均价(元/㎡)</th></tr></thead><tbody>' +
    cc.map((r) => "<tr><td>" + (CITY_NAMES[r.city] || r.city) + "</td><td>" + fmt(r.n_listings) + "</td><td>" + fmt(r.avg_unit_price) + "</td></tr>").join("") +
    "</tbody></table>";
}

document.querySelectorAll("#city-switch button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#city-switch button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    marketState.city = btn.dataset.city;
    if (marketState.trendAll) renderCityView();
  });
});

document.querySelectorAll("#year-switch button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#year-switch button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    marketState.year = btn.dataset.year;
    if (marketState.trendAll) {
      renderTrendArea();
      renderDistrictCompare();
      renderConclusions();
    }
  });
});

/* ---------------- 模型洞察 ---------------- */

async function loadModel() {
  const [health, importance, errors] = await Promise.all([
    jget("/api/health"),
    jget("/api/features/importance"),
    jget("/api/analysis/errors"),
  ]);
  const h = health.holdout || {};
  const o = errors.overall || {};
  const kpis = [
    ["MAE(留出集)", h.mae != null ? fmt(h.mae) + " 元/㎡" : "--"],
    ["MAPE", h.mape_pct != null ? h.mape_pct + "%" : "--"],
    ["误差 ≤10% 占比", o.within_10pct != null ? (o.within_10pct * 100).toFixed(1) + "%" : "--"],
    ["80% 区间覆盖率", o.interval_coverage_80 != null ? (o.interval_coverage_80 * 100).toFixed(1) + "%" : "--"],
  ];
  $("model-kpis").innerHTML = kpis.map(([k, v]) => kpiCard(v, k)).join("");

  const impItems = Object.entries(importance).slice(0, 14).map(([label, value]) => ({ label, value: value * 100 }));
  $("chart-importance").replaceChildren(barChart(impItems, { color: "#a78bfa", formatter: (v) => v.toFixed(1) + "%" }));

  const bp = errors.by_price_band || [];
  $("chart-err-price").replaceChildren(
    barChart(bp.map((r) => ({ label: r.price_band, value: r.mae })).reverse(), { color: "#f59e0b" })
  );
  const bd = (errors.by_district || []).slice(0, 10);
  $("chart-err-district").replaceChildren(
    barChart(bd.map((r) => ({ label: r.district, value: r.mae })), { color: "#f87171" })
  );
}

/* ---------------- Tab 切换 ---------------- */

const loaders = {
  market: () => loadMarket().catch(showErr),
  model: () => loadModel().catch(showErr),
};
const loadedOnce = new Set();

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    tab.classList.add("active");
    const view = "view-" + tab.dataset.view;
    document.getElementById(view).classList.add("active");
    if (loaders[tab.dataset.view] && !loadedOnce.has(tab.dataset.view)) {
      loaders[tab.dataset.view]();
      loadedOnce.add(tab.dataset.view);
    }
  });
});

function showErr(err) {
  console.error(err);
  alert("加载失败: " + err.message);
}

/* ---------------- 启动 ---------------- */

async function boot() {
  // 免费实例冷启动约 50 秒:期间友好提示并自动重试,而不是白屏报错
  const maxTries = 12;
  const delayMs = 6000;
  for (let i = 1; i <= maxTries; i++) {
    try {
      await loadHeader();
      loaders.market();
      loadedOnce.add("market");
      return;
    } catch (err) {
      console.error(err);
      document.getElementById("top-stats").innerHTML =
        '<div class="chip">⏳ 服务唤醒中(免费实例冷启动约 50 秒)· 第 ' + i + " 次重试</div>";
      if (i < maxTries) await new Promise((r) => setTimeout(r, delayMs));
    }
  }
  document.getElementById("top-stats").innerHTML = '<div class="chip">服务暂不可用,请稍后刷新重试</div>';
}

boot();
