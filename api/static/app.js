/* HomeValue 仪表盘:原生 JS + 手写 SVG 图表,无外部依赖 */
"use strict";

const $ = (id) => document.getElementById(id);
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

/* ---------------- SVG 图表(无依赖) ---------------- */

function svgEl(tag, attrs) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
  return el;
}

function barChart(items, opts = {}) {
  // items: [{label, value}];横向条形图
  if (!items || !items.length) return document.createTextNode("暂无数据");
  const width = opts.width || 480;
  const rowH = 24;
  const padL = 90, padR = 70, padT = 8, padB = 8;
  const height = padT + padB + items.length * rowH;
  const max = Math.max(...items.map((d) => d.value)) || 1;
  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, class: "bar-chart" });
  items.forEach((d, i) => {
    const y = padT + i * rowH;
    const w = Math.max(2, (d.value / max) * (width - padL - padR));
    svg.appendChild(svgEl("text", { x: padL - 8, y: y + 15, "text-anchor": "end", class: "bar-label" })).textContent = d.label;
    svg.appendChild(svgEl("rect", { x: padL, y: y + 4, width: w, height: 15, rx: 3, fill: opts.color || "#4f8cff" }));
    const t = svgEl("text", { x: padL + w + 6, y: y + 15, class: "bar-value" });
    t.textContent = (opts.formatter || fmt)(d.value);
    svg.appendChild(t);
  });
  return svg;
}

function lineChart(points, opts = {}) {
  if (!points || points.length < 2) return document.createTextNode("数据不足");
  const width = opts.width || 480, height = opts.height || 210;
  const padL = 62, padR = 14, padT = 14, padB = 34;
  const vals = points.map((p) => p.value);
  const min = Math.min(...vals) * 0.96, max = Math.max(...vals) * 1.02;
  const xs = (i) => padL + (i / (points.length - 1)) * (width - padL - padR);
  const ys = (v) => padT + (1 - (v - min) / (max - min || 1)) * (height - padT - padB);
  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, class: "line-chart" });
  // 网格与 y 轴刻度
  for (let g = 0; g <= 3; g++) {
    const v = min + ((max - min) * g) / 3;
    svg.appendChild(svgEl("line", { x1: padL, x2: width - padR, y1: ys(v), y2: ys(v), stroke: "#24304f", "stroke-width": 1 }));
    const t = svgEl("text", { x: padL - 6, y: ys(v) + 3, "text-anchor": "end" });
    t.textContent = (v / 10000).toFixed(2) + "万";
    svg.appendChild(t);
  }
  const path = points.map((p, i) => `${i ? "L" : "M"}${xs(i).toFixed(1)},${ys(p.value).toFixed(1)}`).join(" ");
  svg.appendChild(svgEl("path", { d: path, fill: "none", stroke: "#34d399", "stroke-width": 2 }));
  points.forEach((p, i) => {
    svg.appendChild(svgEl("circle", { cx: xs(i), cy: ys(p.value), r: 3, fill: "#34d399" }));
    const t = svgEl("text", { x: xs(i), y: height - 12, "text-anchor": "middle" });
    t.textContent = (p.label || "").slice(2); // 22-09 -> 短标签
    svg.appendChild(t);
    if (p.extra) {
      const v = svgEl("text", { x: xs(i), y: ys(p.value) - 8, "text-anchor": "middle", fill: "#fbbf24" });
      v.textContent = p.extra;
      svg.appendChild(v);
    }
  });
  return svg;
}

/* ---------------- 顶部状态 ---------------- */

async function loadHeader() {
  const health = await jget("/api/health");
  const overview = await jget("/api/analysis/overview");
  const h = health.holdout || {};
  const chips = [
    ["在售房源", overview.n_listings ? fmt(overview.n_listings) + " 套" : "--"],
    ["留出集 MAE", h.mae != null ? fmt(h.mae) + " 元/㎡" : "--"],
    ["MAPE", h.mape_pct != null ? h.mape_pct + "%" : "--"],
    ["R²", h.r2 != null ? h.r2 : "--"],
    ["数据后端", health.data_backend === "sqlite" ? "SQLite 实时" : "预计算缓存"],
  ];
  $("top-stats").innerHTML = chips.map(([k, v]) => `<div class="chip">${k} <b>${v}</b></div>`).join("");
  const sel = $("f-district");
  (overview.districts_all || []).forEach((d) => {
    const opt = document.createElement("option");
    opt.value = d.district;
    opt.textContent = `${d.district}(均价 ${fmt(d.avg_unit_price)})`;
    sel.appendChild(opt);
  });
}

/* ---------------- 估值 ---------------- */

$("predict-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("predict-btn");
  btn.disabled = true;
  btn.textContent = "计算中...";
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
    alert("估值失败: " + err.message);
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
    compHtml = `<div class="comp-block">参照 <b>${comps.district.district}</b>:${fmt(comps.district.n)} 套在售,均价 ${fmt(comps.district.avg_price)} 元/㎡</div>`;
  } else if (comps.district_avg_price) {
    compHtml = `<div class="comp-block">该区挂牌均价 <b>${fmt(comps.district_avg_price)}</b> 元/㎡</div>`;
  }
  if (comps.bizcircle) {
    compHtml += `<div class="comp-block">商圈 <b>${comps.bizcircle.name}</b>:${fmt(comps.bizcircle.n)} 套,均价 ${fmt(comps.bizcircle.avg_price)} 元/㎡</div>`;
  }
  $("r-comps").innerHTML = compHtml;
  $("r-meta").textContent = `模型 ${res.model_version} · 目标为单价,总价 = 单价 × 面积`;
}

/* ---------------- 市场分析 ---------------- */

async function loadMarket() {
  const [overview, trend, deciles, changes] = await Promise.all([
    jget("/api/analysis/overview"),
    jget("/api/analysis/trend"),
    jget("/api/analysis/deciles"),
    jget("/api/analysis/price-changes"),
  ]);

  const kpis = [
    ["在售房源", overview.n_listings ? fmt(overview.n_listings) + " 套" : "--"],
    ["最贵区", overview.districts_all?.[0]?.district || "--"],
    ["最高区均价", overview.districts_all?.[0] ? fmt(overview.districts_all[0].avg_unit_price) + " 元/㎡" : "--"],
    ["总价TOP20%房源金额占比", overview.top20_value_share != null ? overview.top20_value_share + "%" : "--"],
  ];
  $("market-kpis").innerHTML = kpis
    .map(([k, v]) => `<div class="kpi"><b>${v}</b><span>${k}</span></div>`)
    .join("");

  $("chart-trend").replaceChildren(
    lineChart(
      trend.map((r) => ({ label: r.snapshot_date, value: r.avg_unit_price, extra: r.mom_pct ? r.mom_pct + "%" : null })),
      { height: 230 }
    )
  );

  const districts = (overview.districts_all || []).slice().reverse();
  $("chart-districts").replaceChildren(
    barChart(districts.map((d) => ({ label: d.district, value: d.avg_unit_price })), { color: "#4f8cff" })
  );

  $("table-deciles").innerHTML =
    '<table><thead><tr><th>分位</th><th>区间(元/㎡)</th><th>均价</th><th>平均面积</th><th>套数</th></tr></thead><tbody>' +
    deciles
      .map(
        (r) =>
          `<tr><td>D${r.decile}</td><td>${fmt(r.price_min)} ~ ${fmt(r.price_max)}</td><td>${fmt(r.avg_unit_price)}</td><td>${r.avg_area}㎡</td><td>${fmt(r.n_listings)}</td></tr>`
      )
      .join("") +
    "</tbody></table>";

  const s = changes.summary?.[0];
  const cc = changes.city_compare || [];
  $("price-changes").innerHTML = `
    <div class="comp-block">跨快照同房源调价 <b>${fmt(s?.n_changed)}</b> 套,平均变动
      <b>${s?.avg_pct_change ?? "--"}%</b>,降价占比 <b>${s?.pct_reduced ?? "--"}%</b></div>
    <table style="margin-top:10px"><thead><tr><th>城市</th><th>套数</th><th>均价(元/㎡)</th></tr></thead><tbody>
      ${cc.map((r) => `<tr><td>${{ bj: "北京", sh: "上海", sz: "深圳", gz: "广州" }[r.city] || r.city}</td><td>${fmt(r.n_listings)}</td><td>${fmt(r.avg_unit_price)}</td></tr>`).join("")}
    </tbody></table>`;
}

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
  $("model-kpis").innerHTML = kpis.map(([k, v]) => `<div class="kpi"><b>${v}</b><span>${k}</span></div>`).join("");

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
loadHeader().then(() => {
  loaders.market();
  loadedOnce.add("market");
}).catch(showErr);
