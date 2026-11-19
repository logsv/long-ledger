"""Self-contained HTML portfolio report (no external assets, no scripts)."""

from __future__ import annotations

from html import escape
from ..charts import CHART_CSS

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6a65;--line:#e4e1d8;--card:#ffffff;
--buy:#1f7a4d;--acc:#4f8f3a;--hold:#7a6f3a;--trim:#b0602a;--sell:#b3261e;--na:#777}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--fg:#ecebe6;--muted:#a19f97;
--line:#33322e;--card:#1f1e1b;--buy:#5cc28f;--acc:#8fc970;--hold:#d1c27a;--trim:#e8975c;--sell:#f07a72;--na:#aaa}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}h1{font-size:24px;margin:0 0 4px}
h2{font-size:18px;margin:32px 0 8px}.muted{color:var(--muted)}.card{background:var(--card);
border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}
.kpi b{display:block;font-size:20px}table{width:100%;border-collapse:collapse;font-size:14px}
.wrap{overflow-x:auto}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600}.num{text-align:right;font-variant-numeric:tabular-nums}
.lbl{font-weight:700}.BUY{color:var(--buy)}.ACCUMULATE{color:var(--acc)}.HOLD{color:var(--hold)}
.TRIM{color:var(--trim)}.SELL{color:var(--sell)}.INSUFFICIENT_DATA,.ETF{color:var(--na)}
ul{margin:4px 0 0 18px;padding:0}.warn{border-left:3px solid var(--trim)}
.good{color:var(--buy);font-weight:650}.bad{color:var(--sell);font-weight:650}.ok{color:var(--hold)}
.missing{color:var(--muted)}.sc td{white-space:nowrap}
"""


def _n(v, digits=0, pct=False):
    if v is None:
        return "–"
    if pct:
        return f"{v * 100:.1f}%"
    return f"{v:,.{digits}f}"


def _list(items) -> str:
    items = [i for i in (items or []) if i]
    if not items:
        return ""
    return "<ul>" + "".join(f"<li>{escape(str(i))}</li>" for i in items) + "</ul>"


def _why(why: dict) -> str:
    """Positive lines with '+', negative with '-', missing inputs as-is."""
    return _list([f"+ {x}" for x in why.get("positive") or []]
                 + [f"- {x}" for x in why.get("negative") or []]
                 + [f"missing: {x}" for x in why.get("missing") or []])


def render(run: dict, charts: dict[str, str] | None = None, sell: str | None = None) -> str:
    """The HTML report. `charts` (from isa.charts.portfolio_charts) adds the Charts section."""
    pv, sigs, tax = run["portfolio"], run["signals"], run["tax"]
    by_sym = {s["symbol"]: s for s in sigs}
    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
           f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>Portfolio Report {escape(run['as_of'])}</title><style>{CSS}{CHART_CSS if charts or sell else ""}</style></head><body><main>",
           f"<h1>Portfolio report</h1><p class='muted'>As of {escape(run['as_of'])}. "
           "Personal use only. Not investment or tax advice. Labels are computed by code from stored data; "
           "you place any order yourself.</p>"]

    labelled = [s for s in sigs if s["label"] in ("BUY", "ACCUMULATE", "HOLD", "TRIM", "SELL")]
    monitoring = not labelled
    held_flags = {s["symbol"]: s.get("flags", []) for s in sigs if s["held"]}
    flagged = sum(1 for f in held_flags.values() if f)
    counts: dict[str, int] = {}
    for s in sigs:
        counts[s["label"]] = counts.get(s["label"], 0) + 1
    out.append("<div class='grid'>")
    out.append(f"<div class='card kpi'><span class='muted'>Portfolio value</span><b>₹{_n(pv['total_value'])}</b></div>")
    out.append(f"<div class='card kpi'><span class='muted'>Holdings</span><b>{len(pv['holdings'])}</b></div>")
    out.append(f"<div class='card kpi'><span class='muted'>Top-5 weight</span><b>{_n(pv['top5_weight'], pct=True)}</b></div>")
    cov = run.get("coverage") or {}
    weights = {h["symbol"]: h.get("weight") or 0 for h in pv["holdings"]}
    full = [s for s, c in cov.items() if c["state"] == "full"]
    out.append(f"<div class='card kpi'><span class='muted'>Company data</span><b>{len(full)} of {len(cov)}</b>"
               f"<span class='muted'>{_n(sum(weights.get(s, 0) for s in full), pct=True)} of value</span></div>")
    if monitoring:
        out.append(f"<div class='card kpi'><span class='muted'>Flagged holdings</span><b>{flagged} of {len(held_flags)}</b></div></div>")
    else:
        out.append("<div class='card kpi'><span class='muted'>Labels</span><b>"
                   + escape(", ".join(f"{k} {v}" for k, v in sorted(counts.items()))) + "</b></div></div>")

    if charts:
        out.append("<h2>Charts</h2>" + charts.get("growth", "")
                   + "<div class='viz-grid2'>" + charts.get("allocation", "") + charts.get("returns", "") + "</div>"
                   + charts.get("tax", "")
                   + "<p class='muted'>Hover a line or bar for values; \"Show data\" lists the numbers.</p>")

    alerts = []
    for b in pv["breaches"]:
        alerts.append(f"{_breach_name(b)} is {b['weight']:.1%} of the portfolio (limit {b['cap']:.0%})")
    for r in pv["reconciliation"]:
        alerts.append(f"{r['account']}: {r['symbol'] or 'all'} - {r['hint']}")
    if pv["missing_price"]:
        alerts.append("No price for: " + ", ".join(pv["missing_price"]))
    if pv.get("unclassified_assets"):
        alerts.append(f"{len(pv['unclassified_assets'])} holdings not yet classified by INDmoney "
                      "(asset class / market cap): run /sync")
    if run["pending_facts"]:
        alerts.append(f"{run['pending_facts']} extracted facts await your confirmation (/import)")
    um = tax.get("unmatched_sells") or []
    if um:
        syms = sorted({u["symbol"] for u in um})
        alerts.append(f"{len(um)} sells ({len(syms)} stocks) have no earlier buy in the imported history, usually "
                      f"stocks bought before your oldest tradebook: realised gains for them are incomplete")
    if alerts:
        out.append("<div class='card warn'><b>Needs attention</b>" + _list(alerts) + "</div>")
    if monitoring:
        out.append("<div class='card'><b>Monitoring mode.</b> No holding has confirmed company data yet, so BUY/SELL "
                   "labels are off. Run <code>/research</code> (top holdings, or by symbol or company name) to fill "
                   "it from companies' own websites. Holdings below are sorted by risk flags; flags are prompts to "
                   "review, not sell signals.</div>")

    mk = run.get("market") or {}
    if mk:
        lines = [e["text"] for e in (mk.get("block") or {}).get("evidence", [])]
        if mk.get("missing"):
            lines.append("Missing index data: " + ", ".join(mk["missing"]))
        out.append(f"<h2>Market</h2><div class='card'><b>Regime: {escape(str(mk.get('regime')))}</b>"
                   + _list(lines) + "</div>")
        if mk.get("sectors"):
            out.append("<div class='wrap'><table><tr><th>Sector index</th><th class='num'>3 months</th>"
                       "<th class='num'>6 months</th></tr>")
            for s in mk["sectors"]:
                out.append(f"<tr><td>{escape(s['index'])}</td><td class='num'>{_n(s['ret_3m'], pct=True)}</td>"
                           f"<td class='num'>{_n(s.get('ret_6m'), pct=True)}</td></tr>")
            out.append("</table></div>")

    if pv.get("asset_classes"):
        out.append("<h2>Allocation</h2><div class='grid'><div class='wrap'><table><tr><th>Asset class</th>"
                   "<th class='num'>Weight</th></tr>")
        for r in pv["asset_classes"]:
            out.append(f"<tr><td>{escape(r['asset_class'])}</td><td class='num'>{_n(r['weight'], pct=True)}</td></tr>")
        out.append("</table></div><div class='wrap'><table><tr><th>Market cap (stocks)</th><th class='num'>Weight</th></tr>")
        for r in pv.get("market_caps", []):
            out.append(f"<tr><td>{escape(r['bucket'])}</td><td class='num'>{_n(r['weight'], pct=True)}</td></tr>")
        out.append("</table></div></div>")

    flag_counts: dict[str, int] = {}
    for fl in held_flags.values():
        for f in fl:
            flag_counts[f["type"]] = flag_counts.get(f["type"], 0) + 1
    out.append("<h2>Holdings</h2>")
    if flag_counts:
        out.append("<p class='muted'>Flags: " + escape(" · ".join(
            f"{FLAG_NAMES.get(k, k)} {v}" for k, v in sorted(flag_counts.items(), key=lambda kv: -kv[1]))) + "</p>")
    holdings = sorted(pv["holdings"], key=lambda h: (-len(held_flags.get(h["symbol"], [])), -(h.get("weight") or 0)))
    if monitoring:
        out.append("<div class='wrap'><table><tr><th>Stock</th><th class='num'>Value</th><th class='num'>Weight</th>"
                   "<th class='num'>P&amp;L</th><th>Brokers</th><th>Status</th><th>Flags</th><th>Trend</th><th>Company data</th></tr>")
        for h in holdings:
            out.append(_monitor_row(h, by_sym.get(h["symbol"], {}), run))
    else:
        out.append("<div class='wrap'><table><tr><th>Stock</th><th class='num'>Value</th><th class='num'>Weight</th>"
                   "<th class='num'>P&amp;L</th><th>Brokers</th><th>Label</th><th class='num'>Conf.</th><th>Why</th>"
                   "<th>Flags</th><th>Triggers / notes</th><th>Company data</th></tr>")
        for h in holdings:
            out.append(_row(h["symbol"], h, by_sym.get(h["symbol"], {}), run))
    out.append("</table></div>")

    out.append(_scorecard_table(holdings, run))

    if sell is not None:
        out.append("<h2>Sell check</h2><p class='muted'>Holdings worth a review: label TRIM or SELL, a sell trigger, "
                   "or two or more concerns across fundamentals, trend, future (your thesis) and team. Hover a status "
                   "for its reason; <code>/sell-review</code> or the dashboard shows the evidence and charts.</p>" + sell)

    watch = [s for s in sigs if not s["held"]]
    if watch:
        out.append("<h2>Watchlist</h2><div class='wrap'><table><tr><th>Stock</th><th>Label</th>"
                   "<th class='num'>Conf.</th><th>Why</th><th>Timing / notes</th></tr>")
        for s in watch:
            why = s.get("why") or {}
            out.append(f"<tr><td>{escape(s['symbol'])}</td><td class='lbl {escape(s['label'])}'>{escape(s['label'])}</td>"
                       f"<td class='num'>{_n(s.get('confidence'))}</td>"
                       f"<td>{_why(why) if s['label'] != 'INSUFFICIENT_DATA' else 'no company data'}</td>"
                       f"<td>{_list([s.get('timing')] + _flag_lines(s) + s.get('notes', []))}</td></tr>")
        out.append("</table></div>")

    if pv["sectors"]:
        out.append("<h2>Sectors</h2><div class='wrap'><table><tr><th>Sector</th><th class='num'>Value</th>"
                   "<th class='num'>Weight</th></tr>")
        for r in pv["sectors"]:
            out.append(f"<tr><td>{escape(r['sector'])}</td><td class='num'>₹{_n(r['value'])}</td>"
                       f"<td class='num'>{_n(r['weight'], pct=True)}</td></tr>")
        out.append("</table></div>")

    out.append(f"<h2>Tax view</h2><p class='muted'>{escape(tax['act'])}: STCG s.196, LTCG s.198. "
               f"LTCG exemption remaining this financial year: ₹{_n(tax['ltcg_exemption_remaining'])}. "
               f"Not modelled: {escape(', '.join(tax['not_modelled']))}.</p>")
    if charts and tax["lots"]:
        out.append("<div class='viz-grid2'>" + charts.get("tax_gains", "") + charts.get("tax_age", "") + "</div>"
                   + charts.get("tax_unlock", ""))
    if tax["lots"]:
        out.append("<div class='wrap'><table><tr><th>Lot</th><th class='num'>Qty</th><th class='num'>Cost</th>"
                   "<th>Term today</th><th class='num'>Gain</th><th class='num'>Est. tax</th><th>Note</th></tr>")
        for lot in tax["lots"]:
            bought = (f"before {lot['acquired_before']} (est.)" if lot.get("estimated") else lot["buy_date"])
            out.append(f"<tr><td>{escape(lot['symbol'])} · {escape(lot['account'])} · {escape(bought)}</td>"
                       f"<td class='num'>{_n(lot['quantity'])}</td><td class='num'>{_n(lot['cost'], 2)}</td>"
                       f"<td>{escape(lot['term_if_sold_today'])}</td><td class='num'>{_n(lot['unrealised_gain'])}</td>"
                       f"<td class='num'>{_n(lot['est_tax_if_sold'])}</td><td>{escape(lot.get('note') or '')}</td></tr>")
        out.append("</table></div>")
    else:
        out.append("<p class='muted'>No tax lots yet: import tradebooks with /import.</p>")
    out.append("</main></body></html>")
    return "".join(out)


SC_COLS = [("P/E", "pe", "x"), ("P/B", "pb", "x"), ("Div. yield", "dividend_yield", "%"),
           ("ROCE", "roce", "%"), ("ROE", "roe", "%"), ("Cash conv.", "cash_conversion", "x"),
           ("Rev. growth", "revenue_cagr", "%"), ("EPS growth", "eps_cagr", "%"),
           ("Debt/eq.", "debt_to_equity", "x"), ("Int. cover", "interest_coverage", "x"), ("Promoter", "promoter", "%")]


def _scorecard_table(holdings: list[dict], run: dict) -> str:
    """Long-investor scorecard: one compact line per stock with company data."""
    cards = run.get("scorecards") or {}
    rows = [(h, cards[h["symbol"]]) for h in sorted(holdings, key=lambda h: -(h.get("weight") or 0))
            if h["symbol"] in cards and cards[h["symbol"]]["filled"] >= 4]
    head = ("<h2>Scorecard</h2><p class='muted'>Is it cheap, a good business, growing and safe? Colours use the same "
            "thresholds as the labels. Return/yr is your annualised return on the shares you hold "
            "(* under a year: total return; est.: some buy dates estimated). Stocks with fewer than 4 metrics are "
            "left out; run <code>/research</code> to fill them.</p>")
    if not rows:
        return head + "<p class='muted'>No stock has enough company data yet.</p>"
    out = [head, "<div class='wrap'><table class='sc'><tr><th>Stock</th><th class='num'>Return/yr</th>"
           + "".join(f"<th class='num'>{escape(t)}</th>" for t, _, _ in SC_COLS) + "</tr>"]
    for h, c in rows:
        m = {x["key"]: x for g in c["groups"] for x in g["metrics"]}
        yr = c.get("your_return") or {}
        v = yr.get("value") if yr.get("value") is not None else yr.get("simple")
        ret = "–" if v is None else (f"{v:+.1f}%" + ("" if yr.get("value") is not None else "*")
                                     + (" est." if yr.get("estimated") else ""))
        cells = []
        for _, key, kind in SC_COLS:
            x = m[key]
            txt = "–" if x["value"] is None else (f"{x['value']:.1f}x" if kind == "x" else f"{x['value']:.1f}%")
            cells.append(f"<td class='num {escape(x['tone'])}' title='{escape(x['text'])}'>{escape(txt)}</td>")
        out.append(f"<tr><td>{escape(h['symbol'])}</td><td class='num' title='{escape(yr.get('text') or '')}'>"
                   f"{escape(ret)}</td>{''.join(cells)}</tr>")
    out.append("</table></div>")
    return "".join(out)


FLAG_NAMES = {"weak_trend": "Weak trend", "deep_drawdown": "Deep drawdown",
              "volume_spike": "Volume spike", "loss_from_cost": "Loss from cost"}


def _breach_name(b: dict) -> str:
    if b["type"] == "stock":
        return f"Stock {b['name']}"
    if b["type"] == "sector":
        return f"Sector {b['name']}"
    return b["name"].capitalize()


def _flag_lines(s: dict) -> list[str]:
    return [f"{FLAG_NAMES.get(f['type'], f['type'])}: {f['detail']}" for f in s.get("flags", [])]


BROKER_NAMES = {"kite": "Zerodha", "fivepaisa": "5paisa", "indmoney": "INDmoney", "manual": "Manual"}


def _broker_cell(h: dict) -> str:
    """Each broker holding the stock, with its quantity (largest first)."""
    by = h.get("by_account") or {a: None for a in h.get("accounts", [])}
    if not by:
        return "<td class='muted'>–</td>"
    items = sorted(by.items(), key=lambda kv: -(kv[1] or 0))
    lines = [f"{BROKER_NAMES.get(a, a)} {_n(q)}" if q is not None else BROKER_NAMES.get(a, a) for a, q in items]
    return "<td>" + "<br>".join(escape(x) for x in lines) + "</td>"


def _stock_cell(h: dict, run: dict) -> str:
    name = (run.get("names") or {}).get(h["symbol"]) or ""
    sub = " · ".join(x for x in (name.title() if name.isupper() else name, _tag(h)) if x)
    return f"<td>{escape(h['symbol'])}<div class='muted'>{escape(sub or h.get('sector') or '')}</div></td>"


def _data_cell(h: dict, run: dict) -> str:
    if h.get("is_etf"):
        return "<td class='muted'>n/a (ETF)</td>"
    c = (run.get("coverage") or {}).get(h["symbol"])
    if not c or c["state"] == "none":
        pend = f" · {c['pending_facts']} pending" if c and c["pending_facts"] else ""
        return f"<td class='muted'>none{pend}</td>"
    bits = [f"{c['annual_years']}y to {c['latest_annual_period']}" if c["annual_years"] else "",
            f"holding {c['latest_shareholding_quarter']}" if c["latest_shareholding_quarter"] else "",
            ", ".join(c["sites"][:1]),
            f"{c['pending_facts']} pending" if c["pending_facts"] else ""]
    return f"<td>{escape(' · '.join(b for b in bits if b))}</td>"


def _tag(h: dict) -> str:
    return " · ".join(x for x in (h.get("asset_class"), h.get("market_cap_bucket")) if x and x != "unknown")


def _monitor_row(h: dict, s: dict, run: dict) -> str:
    status = "ETF" if s.get("label") == "ETF" else "Monitor"
    trend = {"weak": "Weak", "neutral": "Neutral", "strong": "Strong"}.get(
        (s.get("technicals") or {}).get("stance"), "not enough history")
    return (f"<tr>{_stock_cell(h, run)}"
            f"<td class='num'>₹{_n(h.get('value'))}</td><td class='num'>{_n(h.get('weight'), pct=True)}</td>"
            f"<td class='num'>{_n(h.get('unrealised_pct'), pct=True)}</td>{_broker_cell(h)}"
            f"<td class='muted'>{status}</td><td>{_list(_flag_lines(s)) or '<span class=muted>none</span>'}</td>"
            f"<td class='muted'>{escape(trend)}</td>{_data_cell(h, run)}</tr>")


def _row(symbol: str, h: dict, s: dict, run: dict | None = None) -> str:
    run = run or {}
    why = s.get("why") or {}
    trig = [f"{t['type']}: {t['detail']}" for t in s.get("triggers", [])] + s.get("notes", [])
    if s.get("veto"):
        trig.append("governance: " + "; ".join(s["veto"]))
    label = s.get("label", "–")
    why_html = "no company data" if label == "INSUFFICIENT_DATA" else _why(why)
    return (f"<tr>{_stock_cell(h, run)}"
            f"<td class='num'>₹{_n(h.get('value'))}</td><td class='num'>{_n(h.get('weight'), pct=True)}</td>"
            f"<td class='num'>{_n(h.get('unrealised_pct'), pct=True)}</td>{_broker_cell(h)}"
            f"<td class='lbl {escape(label)}'>{escape(label)}</td><td class='num'>{_n(s.get('confidence'))}</td>"
            f"<td>{why_html}</td><td>{_list(_flag_lines(s))}</td>"
            f"<td>{_list(trig)}</td>{_data_cell(h, run)}</tr>")
