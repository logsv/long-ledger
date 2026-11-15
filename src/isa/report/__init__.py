"""Self-contained HTML portfolio report (no external assets, no scripts)."""

from __future__ import annotations

from html import escape

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


def render(run: dict) -> str:
    pv, sigs, tax = run["portfolio"], run["signals"], run["tax"]
    by_sym = {s["symbol"]: s for s in sigs}
    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
           f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>Portfolio Report {escape(run['as_of'])}</title><style>{CSS}</style></head><body><main>",
           f"<h1>Portfolio report</h1><p class='muted'>As of {escape(run['as_of'])}. "
           "Personal use only. Not investment or tax advice. Labels are computed by code from stored data; "
           "you place any order yourself.</p>"]

    counts: dict[str, int] = {}
    for s in sigs:
        counts[s["label"]] = counts.get(s["label"], 0) + 1
    out.append("<div class='grid'>")
    out.append(f"<div class='card kpi'><span class='muted'>Portfolio value</span><b>₹{_n(pv['total_value'])}</b></div>")
    out.append(f"<div class='card kpi'><span class='muted'>Holdings</span><b>{len(pv['holdings'])}</b></div>")
    out.append(f"<div class='card kpi'><span class='muted'>Top-5 weight</span><b>{_n(pv['top5_weight'], pct=True)}</b></div>")
    out.append("<div class='card kpi'><span class='muted'>Labels</span><b>"
               + escape(", ".join(f"{k} {v}" for k, v in sorted(counts.items()))) + "</b></div></div>")

    alerts = []
    for b in pv["breaches"]:
        alerts.append(f"{b['type'].title()} {b['name']} is {b['weight']:.1%} of the portfolio (cap {b['cap']:.0%})")
    for r in pv["reconciliation"]:
        alerts.append(f"{r['account']}: {r['symbol'] or 'all'} - {r['hint']}")
    if pv["missing_price"]:
        alerts.append("No price for: " + ", ".join(pv["missing_price"]))
    if pv.get("unclassified_assets"):
        alerts.append(f"{len(pv['unclassified_assets'])} holdings not yet classified by INDmoney "
                      "(asset class / market cap): run /sync")
    if run["pending_facts"]:
        alerts.append(f"{run['pending_facts']} extracted facts await your confirmation (/import)")
    if alerts:
        out.append("<div class='card warn'><b>Needs attention</b>" + _list(alerts) + "</div>")

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

    out.append("<h2>Holdings</h2><div class='wrap'><table><tr><th>Stock</th><th class='num'>Value</th>"
               "<th class='num'>Weight</th><th class='num'>P&amp;L</th><th>Label</th><th class='num'>Conf.</th>"
               "<th>Why</th><th>Triggers / notes</th></tr>")
    for h in pv["holdings"]:
        s = by_sym.get(h["symbol"], {})
        out.append(_row(h["symbol"], h, s))
    out.append("</table></div>")

    watch = [s for s in sigs if not s["held"]]
    if watch:
        out.append("<h2>Watchlist</h2><div class='wrap'><table><tr><th>Stock</th><th>Label</th>"
                   "<th class='num'>Conf.</th><th>Why</th><th>Timing / notes</th></tr>")
        for s in watch:
            why = s.get("why") or {}
            out.append(f"<tr><td>{escape(s['symbol'])}</td><td class='lbl {escape(s['label'])}'>{escape(s['label'])}</td>"
                       f"<td class='num'>{_n(s.get('confidence'))}</td>"
                       f"<td>{_why(why)}</td>"
                       f"<td>{_list([s.get('timing')] + s.get('notes', []))}</td></tr>")
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
    if tax["lots"]:
        out.append("<div class='wrap'><table><tr><th>Lot</th><th class='num'>Qty</th><th class='num'>Cost</th>"
                   "<th>Term today</th><th class='num'>Gain</th><th class='num'>Est. tax</th><th>Note</th></tr>")
        for lot in tax["lots"]:
            out.append(f"<tr><td>{escape(lot['symbol'])} · {escape(lot['account'])} · {escape(lot['buy_date'])}</td>"
                       f"<td class='num'>{_n(lot['quantity'])}</td><td class='num'>{_n(lot['cost'], 2)}</td>"
                       f"<td>{escape(lot['term_if_sold_today'])}</td><td class='num'>{_n(lot['unrealised_gain'])}</td>"
                       f"<td class='num'>{_n(lot['est_tax_if_sold'])}</td><td>{escape(lot.get('note') or '')}</td></tr>")
        out.append("</table></div>")
    else:
        out.append("<p class='muted'>No tax lots yet: import tradebooks with /import.</p>")
    out.append("</main></body></html>")
    return "".join(out)


def _row(symbol: str, h: dict, s: dict) -> str:
    why = s.get("why") or {}
    trig = ([f"{t['type']}: {t['detail']}" for t in s.get("triggers", [])]
            + [f"flag {f['type']}: {f['detail']}" for f in s.get("flags", [])] + s.get("notes", []))
    if s.get("veto"):
        trig.append("governance: " + "; ".join(s["veto"]))
    label = s.get("label", "–")
    tag = " · ".join(x for x in (h.get("asset_class"), h.get("market_cap_bucket")) if x and x != "unknown")
    return (f"<tr><td>{escape(symbol)}<div class='muted'>{escape(tag or h.get('sector') or '')}</div></td>"
            f"<td class='num'>₹{_n(h.get('value'))}</td><td class='num'>{_n(h.get('weight'), pct=True)}</td>"
            f"<td class='num'>{_n(h.get('unrealised_pct'), pct=True)}</td>"
            f"<td class='lbl {escape(label)}'>{escape(label)}</td><td class='num'>{_n(s.get('confidence'))}</td>"
            f"<td>{_why(why)}</td>"
            f"<td>{_list(trig)}</td></tr>")
