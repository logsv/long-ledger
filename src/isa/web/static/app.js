/* India Stock Analyzer local dashboard. Talks only to this server (127.0.0.1). */
"use strict";

const TOKEN = document.querySelector('meta[name="isa-token"]').content;
const tables = {};
const state = { holdings: [], trades: [], lots: [] };

// ---------- helpers ----------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const inr = (v, d = 0) => (v === null || v === undefined || v === "") ? "–" : "₹" + Number(v).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });
const num = (v, d = 2) => (v === null || v === undefined || v === "") ? "–" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: d });
const pct = (v, d = 1) => (v === null || v === undefined || v === "") ? "–" : (v * 100).toFixed(d) + "%";
const $ = (id) => document.getElementById(id);

async function getJSON(view) {
  const r = await fetch("/api/" + view, { headers: { "Accept": "application/json" } });
  const body = await r.json();
  if (!r.ok) throw new Error(body.error || r.statusText);
  return body;
}

function toast(msg, isErr = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "show" + (isErr ? " err" : "");
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.className = ""), isErr ? 9000 : 5000);
}

function fillSelect(id, values) {
  const sel = $(id);
  const keep = sel.value;
  [...sel.querySelectorAll("option:not(:first-child)")].forEach((o) => o.remove());
  [...new Set(values.filter(Boolean))].sort().forEach((v) => {
    const o = document.createElement("option");
    o.value = v; o.textContent = v; sel.appendChild(o);
  });
  sel.value = keep;
}

// ---------- formatters ----------
const fmtInr = (d) => (cell) => inr(cell.getValue(), d);
const fmtNum = (d) => (cell) => num(cell.getValue(), d);
const fmtPct = (cell) => pct(cell.getValue());
const fmtPnl = (cell) => {
  const v = cell.getValue();
  if (v === null || v === undefined) return "–";
  return `<span class="${v >= 0 ? "pos" : "neg"}">${pct(v)}</span>`;
};
const fmtGain = (cell) => {
  const v = cell.getValue();
  if (v === null || v === undefined) return "–";
  return `<span class="${v >= 0 ? "pos" : "neg"}">${inr(v)}</span>`;
};
const fmtLabel = (cell) => {
  const v = cell.getValue() || "";
  const text = v === "INSUFFICIENT_DATA" ? "Monitor" : v;
  return `<span class="lbl ${esc(v)}">${esc(text)}</span>`;
};
const fmtFlags = (cell) => (cell.getValue() || []).map((f) => `<span class="chip">${esc(f)}</span>`).join("");
const fmtText = (cell) => esc(cell.getValue());

const sum = { bottomCalc: "sum", bottomCalcFormatter: (c) => inr(c.getValue()) };

// ---------- tables ----------
function makeTable(id, columns, extra = {}) {
  const t = new Tabulator("#" + id, {
    data: [],
    columns,
    layout: "fitDataFill",
    height: "calc(100vh - 250px)",
    movableColumns: true,
    placeholder: "No rows",
    columnDefaults: { headerTooltip: true },
    groupStartOpen: true,
    ...extra,
  });
  t.ready = new Promise((resolve) => t.on("tableBuilt", () => { t.built = true; resolve(); }));
  return t;
}

function buildTables() {
  tables.holdings = makeTable("holdings-table", [
    { title: "Symbol", field: "symbol", frozen: true, headerFilter: "input", formatter: fmtText },
    { title: "Company", field: "name", headerFilter: "input", formatter: fmtText, maxWidth: 260 },
    { title: "Brokers", field: "brokers", headerFilter: "input", formatter: fmtText },
    { title: "Value", field: "value", hozAlign: "right", formatter: fmtInr(0), sorter: "number", ...sum },
    { title: "Weight", field: "weight", hozAlign: "right", formatter: fmtPct, sorter: "number" },
    { title: "P&L", field: "pnl_pct", hozAlign: "right", formatter: fmtPnl, sorter: "number" },
    { title: "Qty", field: "quantity", hozAlign: "right", formatter: fmtNum(2) },
    { title: "Avg cost", field: "avg_cost", hozAlign: "right", formatter: fmtInr(2) },
    { title: "Price", field: "price", hozAlign: "right", formatter: fmtInr(2) },
    { title: "Asset", field: "asset_class", headerFilter: "list", headerFilterParams: { valuesLookup: true, clearable: true } },
    { title: "Cap", field: "market_cap", headerFilter: "list", headerFilterParams: { valuesLookup: true, clearable: true } },
    { title: "Sector", field: "sector", headerFilter: "list", headerFilterParams: { valuesLookup: true, clearable: true } },
    { title: "Label", field: "label", formatter: fmtLabel, headerFilter: "list", headerFilterParams: { valuesLookup: true, clearable: true } },
    { title: "Conf.", field: "confidence", hozAlign: "right", sorter: "number" },
    { title: "Flags", field: "flags", formatter: fmtFlags, sorter: (a, b) => (a || []).length - (b || []).length,
      tooltip: (e, cell) => cell.getRow().getData().flag_detail },
    { title: "Trend", field: "trend", headerFilter: "list", headerFilterParams: { valuesLookup: true, clearable: true } },
    { title: "Company data", field: "data_state", headerFilter: "list", headerFilterParams: { valuesLookup: true, clearable: true } },
    { title: "Why / triggers", field: "why", formatter: (c) => esc([c.getValue(), c.getRow().getData().triggers].filter(Boolean).join(" | ")), maxWidth: 360 },
  ], { initialSort: [{ column: "value", dir: "desc" }] });
  tables.holdings.on("rowClick", (e, row) => showSymbol(row.getData().symbol));

  tables.trades = makeTable("trades-table", [
    { title: "Date", field: "date", headerFilter: "input" },
    { title: "Broker", field: "broker", headerFilter: "list", headerFilterParams: { valuesLookup: true, clearable: true } },
    { title: "Symbol", field: "symbol", headerFilter: "input", formatter: fmtText },
    { title: "Company", field: "name", headerFilter: "input", formatter: fmtText, maxWidth: 260 },
    { title: "Side", field: "side", headerFilter: "list", headerFilterParams: { values: ["BUY", "SELL"], clearable: true } },
    { title: "Qty", field: "quantity", hozAlign: "right", formatter: fmtNum(4) },
    { title: "Price", field: "price", hozAlign: "right", formatter: fmtInr(2) },
    { title: "Value", field: "value", hozAlign: "right", formatter: fmtInr(0), ...sum },
    { title: "Source", field: "origin", headerFilter: "list", headerFilterParams: { valuesLookup: true, clearable: true } },
  ], { initialSort: [{ column: "date", dir: "desc" }] });

  tables.lots = makeTable("lots-table", [
    { title: "Symbol", field: "symbol", frozen: true, headerFilter: "input", formatter: fmtText },
    { title: "Company", field: "name", headerFilter: "input", formatter: fmtText, maxWidth: 240 },
    { title: "Broker", field: "broker", headerFilter: "list", headerFilterParams: { valuesLookup: true, clearable: true } },
    { title: "Bought", field: "bought", headerFilter: "input" },
    { title: "Lot type", field: "origin", headerFilter: "list", headerFilterParams: { valuesLookup: true, clearable: true } },
    { title: "Qty", field: "quantity", hozAlign: "right", formatter: fmtNum(4) },
    { title: "Cost", field: "cost", hozAlign: "right", formatter: fmtInr(2) },
    { title: "Price", field: "price", hozAlign: "right", formatter: fmtInr(2) },
    { title: "Gain", field: "gain", hozAlign: "right", formatter: fmtGain, sorter: "number", bottomCalc: "sum", bottomCalcFormatter: (c) => inr(c.getValue()) },
    { title: "Term today", field: "term", headerFilter: "list", headerFilterParams: { valuesLookup: true, clearable: true } },
    { title: "Long-term from", field: "long_term_from" },
    { title: "Days to LT", field: "days_to_long_term", hozAlign: "right", sorter: "number" },
    { title: "Wait until", field: "wait_until" },
    { title: "Est. tax", field: "est_tax", hozAlign: "right", formatter: fmtInr(0), sorter: "number", ...sum },
    { title: "Note", field: "note", formatter: fmtText, maxWidth: 380 },
  ], { initialSort: [{ column: "symbol", dir: "asc" }] });

  for (const [name, t] of Object.entries(tables)) {
    t.on("dataFiltered", (filters, rows) => {
      const c = $({ holdings: "h-count", trades: "t-count", lots: "l-count" }[name]);
      c.textContent = `${rows.length} of ${t.getDataCount()} rows`;
    });
  }
}

// ---------- toolbar filters (combined with the column header filters) ----------
function applyHoldings() {
  const q = $("h-search").value.toLowerCase(), b = $("h-broker").value, a = $("h-asset").value;
  const flagged = $("h-flagged").checked, noetf = $("h-noetf").checked;
  tables.holdings.setFilter((d) =>
    (!q || [d.symbol, d.name, d.sector, d.brokers].join(" ").toLowerCase().includes(q)) &&
    (!b || d.broker_list.includes(b)) && (!a || d.asset_class === a) &&
    (!flagged || d.flag_count > 0) && (!noetf || !d.is_etf));
  tables.holdings.setGroupBy($("h-group").value || false);
}

function applyTrades() {
  const q = $("t-search").value.toLowerCase(), b = $("t-broker").value, s = $("t-side").value;
  const o = $("t-origin").value, from = $("t-from").value, to = $("t-to").value;
  tables.trades.setFilter((d) =>
    (!q || (d.symbol + " " + d.name).toLowerCase().includes(q)) && (!b || d.broker === b) &&
    (!s || d.side === s) && (!o || d.origin === o) && (!from || d.date >= from) && (!to || d.date <= to));
  const g = $("t-group").value;
  tables.trades.setGroupBy(g === "month" ? (d) => d.date.slice(0, 7) : (g || false));
}

function applyLots() {
  const q = $("l-search").value.toLowerCase(), b = $("l-broker").value, term = $("l-term").value;
  const o = $("l-origin").value, wait = $("l-wait").checked;
  tables.lots.setFilter((d) =>
    (!q || (d.symbol + " " + d.name).toLowerCase().includes(q)) && (!b || d.broker === b) &&
    (!term || d.term === term) && (!o || d.origin === o) &&
    (!wait || (d.days_to_long_term !== null && d.days_to_long_term > 0 && d.days_to_long_term <= 30)));
  tables.lots.setGroupBy($("l-group").value || false);
}

function wireToolbars() {
  ["h-search", "h-broker", "h-asset", "h-flagged", "h-noetf", "h-group"].forEach((id) => $(id).addEventListener("input", applyHoldings));
  ["t-search", "t-broker", "t-side", "t-origin", "t-from", "t-to", "t-group"].forEach((id) => $(id).addEventListener("input", applyTrades));
  ["l-search", "l-broker", "l-term", "l-origin", "l-wait", "l-group"].forEach((id) => $(id).addEventListener("input", applyLots));
  document.querySelectorAll("[data-clear]").forEach((btn) => btn.addEventListener("click", () => {
    const name = btn.dataset.clear;
    document.querySelectorAll(`#tab-${name} .toolbar input, #tab-${name} .toolbar select`).forEach((el) => {
      if (el.type === "checkbox") el.checked = false; else el.value = "";
    });
    tables[name].clearHeaderFilter();
    ({ holdings: applyHoldings, trades: applyTrades, lots: applyLots })[name]();
  }));
  document.querySelectorAll("[data-csv]").forEach((btn) => btn.addEventListener("click", () => {
    const name = btn.dataset.csv;
    tables[name].download("csv", `${name}-${new Date().toISOString().slice(0, 10)}.csv`, {}, "active");
  }));
}

function showSymbol(symbol) {
  for (const [name, prefix] of [["trades", "t"], ["lots", "l"]]) {
    $(prefix + "-search").value = symbol;
  }
  applyTrades(); applyLots();
  switchTab("trades");
  toast(`Showing trades and tax lots for ${symbol}. Clear the search box to see all.`);
}

// ---------- overview ----------
function bars(el, rows) {
  el.innerHTML = rows.length ? rows.map((r) =>
    `<div class="bar"><span>${esc(r.name)}</span><span class="track"><span class="fill" style="width:${Math.min(100, r.weight * 100)}%"></span></span><span class="pct">${pct(r.weight)}</span></div>`).join("")
    : '<span class="muted">No data</span>';
}

function list(items) {
  return items.length ? `<ul class="plain">${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>` : '<span class="muted">Nothing</span>';
}

function renderOverview(o) {
  $("status").textContent = `As of ${o.as_of} · data loaded ${o.computed_at?.replace("T", " ") ?? ""}`;
  const labels = Object.entries(o.labels).map(([k, v]) => `${k === "INSUFFICIENT_DATA" ? "Monitor" : k} ${v}`).join(", ");
  const cards = [
    ["Portfolio value", inr(o.total_value), `${o.holdings} holdings`],
    ["Top-5 weight", pct(o.top5_weight), "concentration"],
    ["Market regime", o.regime || "–", o.market_missing.length ? "index data missing" : "Kite indices + India VIX"],
    ["Flagged holdings", `${o.flagged} of ${o.holdings}`, "review prompts, not signals"],
    ["Company data", `${o.company_data.full} of ${o.company_data.of}`, `${pct(o.company_data.value_share)} of value`],
    ["LTCG exemption left", inr(o.tax.ltcg_exemption_remaining), `${o.tax.wait_lots} lots turn long-term in 30 days`],
    ["Labels", labels || "–", "computed by code"],
  ];
  $("cards").innerHTML = cards.map(([k, v, s]) => `<div class="card"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join("");
  $("market").innerHTML = `<b>Regime: ${esc(o.regime || "unknown")}</b>` + list(o.market_lines.concat(o.market_missing.map((m) => "Missing index data: " + m)));
  const attention = o.breaches.map((b) => `${b.what} is ${pct(b.weight)} of the portfolio (limit ${pct(b.limit, 0)})`)
    .concat(o.reconciliation.map((r) => `${r.broker}${r.symbol ? " " + r.symbol : ""}: ${r.note}`))
    .concat(o.tax.unmatched_sells ? [`${o.tax.unmatched_sells} sells have no earlier buy in the imported history`] : [])
    .concat(o.pending_facts ? [`${o.pending_facts} extracted facts await confirmation`] : []);
  $("attention").innerHTML = list(attention);
  bars($("asset-classes"), o.asset_classes);
  bars($("market-caps"), o.market_caps);
  $("brokers").innerHTML = list(o.synced.map((s) => `${s.broker}: holdings ${s.holdings_as_of}, last trade ${s.last_trade || "none"}`));
  if (!tables.sectors) {
    tables.sectors = new Tabulator("#sectors-table", {
      data: [], placeholder: "No sector index data yet: run /sync in Claude Code",
      layout: "fitColumns",
      columns: [
        { title: "Index", field: "index" },
        { title: "3 months", field: "ret_3m", hozAlign: "right", formatter: fmtPnl, sorter: "number" },
        { title: "6 months", field: "ret_6m", hozAlign: "right", formatter: fmtPnl, sorter: "number" },
      ],
    });
    tables.sectors.on("tableBuilt", () => { tables.sectors.built = true; tables.sectors.replaceData(o.sectors); });
  } else if (tables.sectors.built) {
    tables.sectors.replaceData(o.sectors);
  }
  $("tax-note").textContent = `LTCG exemption left this financial year: ${inr(o.tax.ltcg_exemption_remaining)}. ` +
    `"Unknown" term = buy date unknown, shown at the STCG rate as a worst case. Loss set-off, grandfathering and STT are not modelled.`;
}

function renderQuality(q) {
  const simple = (id, data, columns) => {
    if (tables[id]) return tables[id].built && tables[id].replaceData(data);
    const t = new Tabulator("#" + id, { data, columns, layout: "fitDataFill", placeholder: "Nothing", maxHeight: 360 });
    t.on("tableBuilt", () => { t.built = true; });
    tables[id] = t;
  };
  simple("q-recon", q.reconciliation, [{ title: "Broker", field: "broker" }, { title: "Stock", field: "symbol" }, { title: "Note", field: "note", formatter: fmtText }]);
  simple("q-unmatched", q.unmatched_sells, [{ title: "Broker", field: "broker", headerFilter: "input" }, { title: "Stock", field: "symbol", headerFilter: "input" },
    { title: "Company", field: "name", formatter: fmtText }, { title: "Sell date", field: "sell_date" }, { title: "Unmatched qty", field: "quantity", hozAlign: "right" }]);
  simple("q-pending", q.pending_facts, [{ title: "Stock", field: "symbol" }, { title: "Metric", field: "metric" }, { title: "Period", field: "period_end" },
    { title: "Value", field: "value", hozAlign: "right" }, { title: "Document", field: "source" }, { title: "Source", field: "source_ref", formatter: fmtText }]);
  $("q-other").innerHTML = list([
    q.unclassified.length ? `Not classified by INDmoney: ${q.unclassified.join(", ")}` : "All holdings classified",
    q.missing_price.length ? `No price: ${q.missing_price.join(", ")}` : "All holdings priced",
  ]);
}

// ---------- loading ----------
async function loadAll() {
  try {
    await Promise.all(["holdings", "trades", "lots"].map((n) => tables[n].ready));
    const [o, h, t, l, q] = await Promise.all(["overview", "holdings", "trades", "lots", "quality"].map(getJSON));
    renderOverview(o);
    state.holdings = h; state.trades = t; state.lots = l;
    await tables.holdings.replaceData(h);
    await tables.trades.replaceData(t);
    await tables.lots.replaceData(l);
    fillSelect("h-broker", h.flatMap((r) => r.broker_list));
    fillSelect("h-asset", h.map((r) => r.asset_class));
    fillSelect("t-broker", t.map((r) => r.broker));
    fillSelect("t-origin", t.map((r) => r.origin));
    fillSelect("l-broker", l.map((r) => r.broker));
    fillSelect("l-origin", l.map((r) => r.origin));
    applyHoldings(); applyTrades(); applyLots();
    renderQuality(q);
  } catch (err) {
    toast("Could not load data: " + err.message, true);
    $("status").textContent = "Load failed";
  }
}

async function runAction(btn) {
  const name = btn.dataset.action;
  document.querySelectorAll("[data-action]").forEach((b) => (b.disabled = true));
  const old = btn.textContent;
  btn.textContent = "Working…";
  try {
    const r = await fetch("/api/action/" + name, { method: "POST", headers: { "X-ISA-Token": TOKEN } });
    const body = await r.json();
    if (!r.ok || body.ok === false) throw new Error(body.message || body.error || r.statusText);
    toast(body.message);
    await loadAll();
  } catch (err) {
    toast(err.message, true);
  } finally {
    btn.textContent = old;
    document.querySelectorAll("[data-action]").forEach((b) => (b.disabled = false));
  }
}

function switchTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("active", s.id === "tab-" + name));
  // only redraw tables that finished building and are on the visible tab
  Object.values(tables).forEach((t) => { if (t.built && t.element.offsetParent !== null) t.redraw(true); });
  try { localStorage.setItem("isa-tab", name); } catch (e) { /* storage unavailable */ }
}

document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));
document.querySelectorAll("[data-action]").forEach((b) => b.addEventListener("click", () => runAction(b)));
buildTables();
wireToolbars();
let startTab = "overview";
try { startTab = localStorage.getItem("isa-tab") || "overview"; } catch (e) { /* ignore */ }
switchTab(startTab);
loadAll();
