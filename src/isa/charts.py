"""Long-investor charts as self-contained HTML + SVG, shared by the HTML report and the dashboard.

No scripts: every chart is plain SVG with native hover tooltips (<title>), a legend,
direct labels and a "Show data" table, so it works in the static report, prints, and
reads without colour. Colours come from CSS classes (CHART_CSS) with light and dark
values; the categorical slots are the validated blue / orange / aqua set, and gains
and losses use the reserved good / critical status colours together with a +/− sign.

Charts:
  growth      value of today's holdings vs money invested vs the same money in NIFTY 500
  allocation  sector, market cap and gold + silver weights against your limits
  returns     your yearly return per stock (best and worst)
  tax         lots turning long-term in the next 90 days, with the tax if sold before
  business    per stock: revenue and profit by year, ROCE by year
  pe_band     per stock: P/E at each annual filing vs its median
  price       per stock: weekly price, 200-day average, your buys and sells
"""

from __future__ import annotations

import bisect
import math
from datetime import date, timedelta
from html import escape

from .engine.base import Data, median
from .scorecard import xirr

BENCHMARK = "NIFTY 500"

CHART_CSS = """
.viz-fig{--v1:#2a78d6;--v2:#eb6834;--v3:#1baf7a;--good:#0ca30c;--bad:#d03b3b;--warn:#fab219;
--ink:currentColor;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--surf:#fcfcfb;
margin:0 0 18px;min-width:0}
@media (prefers-color-scheme:dark){.viz-fig{--v1:#3987e5;--v2:#d95926;--v3:#199e70;--good:#0ca30c;
--bad:#e66767;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--surf:#1a1a19}}
.viz-fig h3{font-size:15px;margin:0 0 2px}.viz-sub{color:var(--ink2);font-size:12.5px;margin:0 0 6px}
.viz-legend{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12.5px;color:var(--ink2);margin:0 0 4px}
.viz-key{display:inline-block;width:14px;height:3px;border-radius:2px;vertical-align:middle;margin-right:5px}
.viz-key.dot{width:9px;height:9px;border-radius:50%}
.viz-svg{width:100%;height:auto;display:block;overflow:visible;font:11px system-ui,-apple-system,"Segoe UI",sans-serif;max-width:var(--viz-max,760px)}
.viz-svg.wide{--viz-max:900px}.viz-svg.bars{--viz-max:560px}.viz-svg.cols{--viz-max:360px}
.viz-svg text{fill:var(--muted)}.viz-svg .vlbl{fill:var(--ink2)}.viz-svg .vval{fill:var(--ink2);font-variant-numeric:tabular-nums}
.viz-svg .grid{stroke:var(--grid);stroke-width:1}.viz-svg .axis{stroke:var(--axis);stroke-width:1}
.viz-svg .ln{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.viz-svg .dash{stroke-dasharray:4 3}
.s1{stroke:var(--v1)}.s2{stroke:var(--v2)}.s3{stroke:var(--v3)}.sm{stroke:var(--muted)}
.f1{fill:var(--v1)}.f2{fill:var(--v2)}.f3{fill:var(--v3)}.fgood{fill:var(--good)}.fbad{fill:var(--bad)}
.fband{fill:var(--v1);opacity:.14}
.bg1{background:var(--v1)}.bg2{background:var(--v2)}.bg3{background:var(--v3)}.bgm{background:var(--muted)}
.bggood{background:var(--good)}.bgbad{background:var(--bad)}
.viz-svg .mk{stroke:var(--surf);stroke-width:2}
.viz-svg .hit{fill:transparent}.viz-svg .hit:hover{fill:var(--ink2);opacity:.08}
.viz-svg .limit{stroke:var(--ink2);stroke-width:2}
.viz-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:4px 0 10px}
.viz-tile{border:1px solid var(--grid);border-radius:8px;padding:8px 10px}
.viz-tile .k{color:var(--ink2);font-size:12px}.viz-tile .v{font-size:19px;font-weight:650}
.viz-tile .s{color:var(--muted);font-size:11.5px}
.viz-up{color:var(--good)}.viz-down{color:var(--bad)}
.viz-fig details{margin-top:4px;font-size:12.5px}.viz-fig summary{cursor:pointer;color:var(--ink2)}
.viz-fig table{border-collapse:collapse;width:100%;margin-top:4px}
.viz-fig th,.viz-fig td{padding:3px 6px;border-bottom:1px solid var(--grid);text-align:left}
.viz-fig td.n,.viz-fig th.n{text-align:right;font-variant-numeric:tabular-nums}
.viz-empty{color:var(--muted);font-size:13px;padding:10px 0}
.viz-grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:4px 22px}
"""


# ---------------------------------------------------------------- formatting
def inr(v: float | None, short: bool = True) -> str:
    """Indian number style: ₹60.8L, ₹1.25Cr, ₹45.3K, ₹950."""
    if v is None:
        return "–"
    sign, a = ("−" if v < 0 else ""), abs(v)
    if short and a >= 1e7:
        return f"{sign}₹{a / 1e7:.2f}Cr"
    if short and a >= 1e5:
        return f"{sign}₹{a / 1e5:.1f}L"
    if short and a >= 1e3:
        return f"{sign}₹{a / 1e3:.1f}K"
    return f"{sign}₹{a:,.0f}"


def pct(v: float | None, signed: bool = True, digits: int = 1) -> str:
    if v is None:
        return "–"
    s = f"{abs(v):.{digits}f}%"
    return (("+" if v > 0 else "−" if v < 0 else "") + s) if signed else s


def _ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = (lo // step) * step
    out, t = [], start
    while t <= hi + step * 0.001:
        out.append(round(t, 10))
        t += step
    return out


def _fig(title: str, sub: str, body: str, legend: list[tuple[str, str]] | None = None,
         table: tuple[list[str], list[list[str]]] | None = None, tiles: str = "") -> str:
    leg = ""
    if legend and len(legend) >= 2:
        leg = "<div class='viz-legend'>" + "".join(
            f"<span><i class='viz-key {escape(c)}'></i>{escape(n)}</span>" for n, c in legend) + "</div>"
    tbl = ""
    if table:
        head, rows = table
        tbl = ("<details><summary>Show data</summary><table><tr>" +
               "".join(f"<th class='{'n' if i else ''}'>{escape(h)}</th>" for i, h in enumerate(head)) + "</tr>" +
               "".join("<tr>" + "".join(f"<td class='{'n' if i else ''}'>{escape(c)}</td>" for i, c in enumerate(r))
                       + "</tr>" for r in rows) + "</table></details>")
    return (f"<figure class='viz-fig'><h3>{escape(title)}</h3><p class='viz-sub'>{escape(sub)}</p>"
            f"{tiles}{leg}{body}{tbl}</figure>")


def _empty(title: str, why: str) -> str:
    return f"<figure class='viz-fig'><h3>{escape(title)}</h3><p class='viz-empty'>{escape(why)}</p></figure>"


# ---------------------------------------------------------------- SVG primitives
def _line_svg(dates: list[str], series: list[dict], y_fmt=inr, w: int = 720, h: int = 260,
              markers: list[dict] | None = None, band: tuple[list[float], list[float]] | None = None,
              y_range: tuple[float, float] | None = None, zero_line: bool = False) -> str:
    """Time-series lines on one y-axis. series: [{name, cls, values}] aligned with dates."""
    left, right, top, bottom = 62, 92, 10, 24
    pw, ph = w - left - right, h - top - bottom
    vals = [v for s in series for v in s["values"] if v is not None]
    if markers:
        vals += [m["y"] for m in markers]
    lo, hi = min(vals), max(vals)
    nonneg = lo >= 0
    pad = (hi - lo) * 0.06 or abs(hi) * 0.05 or 1
    lo, hi = lo - pad, hi + pad
    if nonneg and lo < (hi - lo) * 0.6:
        lo = 0.0  # start money and price axes at zero when the data is near it
    if y_range:
        lo, hi = y_range
        nonneg = False
    ticks = [t for t in _ticks(lo, hi) if not nonneg or t >= 0]
    lo, hi = min(lo, ticks[0]), max(hi, ticks[-1])
    n = len(dates)
    x = lambda i: left + (pw * i / (n - 1) if n > 1 else pw / 2)  # noqa: E731
    y = lambda v: top + ph - (v - lo) / (hi - lo) * ph  # noqa: E731
    out = [f"<svg class='viz-svg{' wide' if w >= 900 else ''}' viewBox='0 0 {w} {h}' role='img'>"]
    for t in ticks:
        out.append(f"<line class='grid' x1='{left}' x2='{left + pw}' y1='{y(t):.1f}' y2='{y(t):.1f}'/>"
                   f"<text x='{left - 6}' y='{y(t) + 4:.1f}' text-anchor='end'>{escape(y_fmt(t))}</text>")
    out.append(f"<line class='axis' x1='{left}' x2='{left + pw}' y1='{top + ph}' y2='{top + ph}'/>")
    if zero_line and lo < 0 < hi:
        out.append(f"<line class='axis' x1='{left}' x2='{left + pw}' y1='{y(0):.1f}' y2='{y(0):.1f}'/>")
    # month/year ticks: about 6 labels
    step = max(1, n // 6)
    for i in range(0, n, step):
        d = dates[i]
        lab = date.fromisoformat(d).strftime("%b %y")
        out.append(f"<text x='{x(i):.1f}' y='{h - 6}' text-anchor='middle'>{lab}</text>")
    if band:
        lo_b, hi_b = band
        pts = [f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(hi_b)] + \
              [f"{x(i):.1f},{y(v):.1f}" for i, v in reversed(list(enumerate(lo_b)))]
        out.append(f"<polygon class='fband' points='{' '.join(pts)}'/>")
    ends = []
    for s in series:
        pts = [(x(i), y(v)) for i, v in enumerate(s["values"]) if v is not None]
        if not pts:
            continue
        d = "M" + " L".join(f"{a:.1f},{b:.1f}" for a, b in pts)
        out.append(f"<path class='ln {escape(s['cls'])}{' dash' if s.get('dash') else ''}' d='{d}'/>")
        last = next(v for v in reversed(s["values"]) if v is not None)
        ends.append([pts[-1][1], s, last])
    # direct labels at the line ends, nudged apart
    ends.sort(key=lambda e: e[0])
    for i in range(1, len(ends)):
        if ends[i][0] - ends[i - 1][0] < 13:
            ends[i][0] = ends[i - 1][0] + 13
    for yy, s, last in ends:
        out.append(f"<text class='vlbl' x='{left + pw + 6}' y='{yy + 4:.1f}'>{escape(s.get('short', s['name']))} "
                   f"<tspan class='vval'>{escape(y_fmt(last))}</tspan></text>")
    for m in markers or []:
        i = m["i"]
        tri = (f"{x(i):.1f},{y(m['y']) - 7:.1f} {x(i) - 6:.1f},{y(m['y']) + 4:.1f} {x(i) + 6:.1f},{y(m['y']) + 4:.1f}"
               if m["kind"] == "buy" else
               f"{x(i):.1f},{y(m['y']) + 7:.1f} {x(i) - 6:.1f},{y(m['y']) - 4:.1f} {x(i) + 6:.1f},{y(m['y']) - 4:.1f}")
        out.append(f"<polygon class='mk {'fgood' if m['kind'] == 'buy' else 'fbad'}' points='{tri}'>"
                   f"<title>{escape(m['title'])}</title></polygon>")
    # hover: one column per date, tooltip lists every series
    colw = pw / max(n - 1, 1)
    for i, d in enumerate(dates):
        tip = date.fromisoformat(d).strftime("%d %b %Y") + "".join(
            f"\n{s['name']}: {y_fmt(s['values'][i])}" for s in series if s["values"][i] is not None)
        out.append(f"<rect class='hit' x='{x(i) - colw / 2:.1f}' y='{top}' width='{colw:.1f}' height='{ph}'>"
                   f"<title>{escape(tip)}</title></rect>")
    out.append("</svg>")
    return "".join(out)


def _hbar_svg(rows: list[dict], w: int = 520, fmt=pct, label_w: int = 150, diverging: bool = False) -> str:
    """Horizontal bars. rows: [{label, value, cls, title, limit?, note?}]."""
    bar_h, gap, top = 16, 8, 4
    h = top + len(rows) * (bar_h + gap) + 4
    vw = w - label_w - 70
    vals = [r["value"] for r in rows] + [r["limit"] for r in rows if r.get("limit") is not None]
    if diverging:
        m = max(abs(v) for v in vals) or 1
        lo, hi = -m, m
    else:
        lo, hi = 0.0, max(vals) or 1
    x = lambda v: label_w + (v - lo) / (hi - lo) * vw  # noqa: E731
    out = [f"<svg class='viz-svg bars' viewBox='0 0 {w} {h}' role='img'>"]
    zero = x(0)
    for i, r in enumerate(rows):
        yy = top + i * (bar_h + gap)
        a, b = sorted((zero, x(r["value"])))
        width = max(b - a, 1.5)
        out.append(f"<text class='vlbl' x='{label_w - 8}' y='{yy + bar_h - 4}' text-anchor='end'>{escape(r['label'])}</text>")
        out.append(f"<rect class='{escape(r['cls'])}' x='{a:.1f}' y='{yy}' width='{width:.1f}' height='{bar_h}' rx='3'>"
                   f"<title>{escape(r['title'])}</title></rect>")
        if r.get("limit") is not None:
            lx = x(r["limit"])
            out.append(f"<line class='limit' x1='{lx:.1f}' x2='{lx:.1f}' y1='{yy - 3}' y2='{yy + bar_h + 3}'>"
                       f"<title>Limit {escape(fmt(r['limit']))}</title></line>")
        tx = (b + 6) if r["value"] >= 0 or not diverging else (a - 6)
        anchor = "start" if r["value"] >= 0 or not diverging else "end"
        if r.get("limit") is not None:
            tx = max(tx, x(r["limit"]) + 6)
        out.append(f"<text class='vval' x='{tx:.1f}' y='{yy + bar_h - 4}' text-anchor='{anchor}'>"
                   f"{escape(fmt(r['value']))}{escape(r.get('note', ''))}</text>")
    if diverging:
        out.append(f"<line class='axis' x1='{zero:.1f}' x2='{zero:.1f}' y1='0' y2='{h}'/>")
    out.append("</svg>")
    return "".join(out)


def _columns_svg(labels: list[str], values: list[float | None], fmt, w: int = 340, h: int = 150, cls: str = "f1") -> str:
    left, top, bottom = 8, 16, 20
    pw, ph = w - left * 2, h - top - bottom
    vals = [v for v in values if v is not None]
    if not vals:
        return ""
    hi, lo = max(max(vals), 0), min(min(vals), 0)
    rng = (hi - lo) or 1
    y = lambda v: top + ph - (v - lo) / rng * ph  # noqa: E731
    n = len(labels)
    slot = pw / n
    bw = min(slot - 6, 34)
    out = [f"<svg class='viz-svg cols' viewBox='0 0 {w} {h}' role='img'>",
           f"<line class='axis' x1='{left}' x2='{left + pw}' y1='{y(0):.1f}' y2='{y(0):.1f}'/>"]
    for i, (lab, v) in enumerate(zip(labels, values)):
        cx = left + slot * i + slot / 2
        out.append(f"<text x='{cx:.1f}' y='{h - 5}' text-anchor='middle'>{escape(lab)}</text>")
        if v is None:
            continue
        a, b = sorted((y(0), y(v)))
        c = cls if v >= 0 else "fbad"
        out.append(f"<rect class='{c}' x='{cx - bw / 2:.1f}' y='{a:.1f}' width='{bw:.1f}' height='{max(b - a, 1):.1f}' rx='3'>"
                   f"<title>{escape(lab)}: {escape(fmt(v))}</title></rect>")
        if i in (0, n - 1):  # selective labels: first and latest
            ty = a - 4 if v >= 0 else b + 11
            out.append(f"<text class='vval' x='{cx:.1f}' y='{ty:.1f}' text-anchor='middle'>{escape(fmt(v))}</text>")
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- data helpers
def _lots_scaled(run: dict) -> list[dict]:
    """Open lots with cost scaled to the broker's cost per stock (the figure P&L uses)."""
    pos = {h["symbol"]: h for h in run["portfolio"]["holdings"]}
    lots = [l for l in run["tax"]["lots"] if l.get("cost_known", True) and l.get("cost")]
    lot_cost: dict[str, float] = {}
    for l in lots:
        lot_cost[l["symbol"]] = lot_cost.get(l["symbol"], 0.0) + l["quantity"] * l["cost"]
    out = []
    for l in lots:
        p = pos.get(l["symbol"])
        k = (p["cost"] / lot_cost[l["symbol"]]) if (p and p.get("cost_known") and p.get("cost")
                                                    and lot_cost.get(l["symbol"])) else 1.0
        d = l.get("acquired_before") if l.get("estimated") else l.get("buy_date")
        if d:
            out.append({**l, "date": d[:10], "amount": l["quantity"] * l["cost"] * k})
    return out


def growth_data(conn, run: dict, as_of: date) -> dict | None:
    lots = _lots_scaled(run)
    if not lots:
        return None
    d = Data(conn, as_of)
    start = date.fromisoformat(min(l["date"] for l in lots))
    days = [start + timedelta(days=7 * i) for i in range(((as_of - start).days // 7) + 1)]
    if not days or days[-1] != as_of:
        days.append(as_of)
    bdates, bclose, _ = d.closes(BENCHMARK)
    if not bdates:
        return None

    def bench(on: str) -> float:
        i = bisect.bisect_right(bdates, on)
        return bclose[i - 1] if i else bclose[0]

    units = [l["amount"] / bench(l["date"]) for l in lots]
    today_px = {h["symbol"]: h["price"] for h in run["portfolio"]["holdings"] if h.get("price")}
    value, invested, index_v = [], [], []
    for day in days:
        iso = day.isoformat()
        v = inv = b = 0.0
        for l, u in zip(lots, units):
            if l["date"] > iso:
                continue
            # the last point uses the portfolio's own price (broker price first), so it matches the total
            px = today_px.get(l["symbol"]) if day == as_of else d.price_on(l["symbol"], iso)
            v += l["quantity"] * px if px else l["amount"]
            inv += l["amount"]
            b += u * bench(iso)
        value.append(round(v, 0))
        invested.append(round(inv, 0))
        index_v.append(round(b, 0))
    flows = [(date.fromisoformat(l["date"]), -l["amount"]) for l in lots]
    you = xirr(flows + [(as_of, value[-1])])
    idx = xirr(flows + [(as_of, index_v[-1])])
    return {"dates": [x.isoformat() for x in days], "value": value, "invested": invested, "index": index_v,
            "xirr_you": you, "xirr_index": idx, "estimated": any(l.get("estimated") for l in lots),
            "first": start.isoformat(), "prices_from": bdates[0]}


# ---------------------------------------------------------------- portfolio charts
def growth_chart(conn, run: dict, as_of: date) -> str:
    title = f"Your holdings vs money invested vs {BENCHMARK}"
    g = growth_data(conn, run, as_of)
    if not g:
        return _empty(title, f"Needs tax lots and {BENCHMARK} prices: run /sync and /import tradebooks.")
    gain = g["value"][-1] - g["invested"][-1]
    beat = (g["xirr_you"] - g["xirr_index"]) if g["xirr_you"] is not None and g["xirr_index"] is not None else None

    def tile(k, v, s="", cls=""):
        return f"<div class='viz-tile'><div class='k'>{escape(k)}</div><div class='v {cls}'>{escape(v)}</div><div class='s'>{escape(s)}</div></div>"
    tiles = ("<div class='viz-tiles'>" +
             tile("Value today", inr(g["value"][-1]), f"invested {inr(g['invested'][-1])}") +
             tile("Gain", inr(gain), pct(gain / g["invested"][-1] * 100 if g["invested"][-1] else None),
                  "viz-up" if gain >= 0 else "viz-down") +
             tile("Your return per year", pct(g["xirr_you"] * 100 if g["xirr_you"] is not None else None),
                  "annualised, from your buy dates") +
             tile(f"{BENCHMARK}, same dates", pct(g["xirr_index"] * 100 if g["xirr_index"] is not None else None),
                  ("you are ahead by " if (beat or 0) >= 0 else "you are behind by ") + pct(abs(beat) * 100, False)
                  + " a year" if beat is not None else "", "") + "</div>")
    series = [{"name": "Your holdings", "short": "Holdings", "cls": "s1", "values": g["value"]},
              {"name": f"Same money in {BENCHMARK}", "short": "NIFTY 500", "cls": "s2", "values": g["index"]},
              {"name": "Money invested", "short": "Invested", "cls": "s3", "values": g["invested"], "dash": True}]
    sub = ("Shares you hold today, valued each week from their buy dates; sold shares are not included. "
           f"The {BENCHMARK} line puts each buy's amount into the index on the same day.")
    if g["estimated"]:
        sub += " Some buy dates are estimated (bought before your earliest imported trade)."
    if g["first"] < g["prices_from"]:
        sub += f" Prices start {g['prices_from']}, so earlier weeks use cost."
    rows = [[dd, inr(v, False), inr(b, False), inr(i, False)]
            for dd, v, b, i in zip(g["dates"], g["value"], g["index"], g["invested"])][::-4][::-1]
    return _fig(title, sub, _line_svg(g["dates"], series, w=900, h=300),
                legend=[("Your holdings", "bg1"), (f"Same money in {BENCHMARK}", "bg2"), ("Money invested (dashed)", "bg3")],
                table=(["Week", "Holdings", BENCHMARK, "Invested"], rows), tiles=tiles)


def allocation_chart(run: dict, thresholds: dict) -> str:
    pv, caps = run["portfolio"], thresholds["portfolio"]
    rows = []
    for r in pv["sectors"][:8]:
        if r["sector"] == "Unclassified":
            continue
        over = r["weight"] > caps["max_sector_weight"]
        rows.append({"label": r["sector"][:24], "value": r["weight"] * 100, "limit": caps["max_sector_weight"] * 100,
                     "cls": "fbad" if over else "f1", "note": "  over limit" if over else "",
                     "title": f"{r['sector']}: {r['weight']:.1%} of the portfolio (limit {caps['max_sector_weight']:.0%})"})
    caps_w = {r["bucket"]: r["weight"] for r in pv["market_caps"]}
    sc = caps_w.get("small", 0.0)
    rows.append({"label": "Small caps", "value": sc * 100, "limit": caps["max_small_cap_weight"] * 100,
                 "cls": "fbad" if sc > caps["max_small_cap_weight"] else "f1",
                 "note": "  over limit" if sc > caps["max_small_cap_weight"] else "",
                 "title": f"Small caps: {sc:.1%} (limit {caps['max_small_cap_weight']:.0%})"})
    pm = sum(r["weight"] for r in pv["asset_classes"] if r["asset_class"] in ("gold", "silver"))
    rows.append({"label": "Gold + silver", "value": pm * 100, "limit": caps["max_precious_metals_weight"] * 100,
                 "cls": "fbad" if pm > caps["max_precious_metals_weight"] else "f1",
                 "note": "  over limit" if pm > caps["max_precious_metals_weight"] else "",
                 "title": f"Gold + silver: {pm:.1%} (limit {caps['max_precious_metals_weight']:.0%})"})
    unc = next((r["weight"] for r in pv["sectors"] if r["sector"] == "Unclassified"), 0)
    sub = "Share of portfolio value. The vertical mark is your limit; red bars are over it."
    if unc:
        sub += f" {unc:.0%} of value has no sector yet (run /research)."
    table = (["Group", "Weight", "Limit"], [[r["label"], pct(r["value"], False), pct(r["limit"], False, 0)] for r in rows])
    return _fig("Allocation against your limits", sub, _hbar_svg(rows, fmt=lambda v: pct(v, False)), table=table)


def returns_chart(run: dict, n: int = 8) -> str:
    title = "Your return per year, best and worst"
    cards = run.get("scorecards") or {}
    items = []
    for sym, c in cards.items():
        yr = c.get("your_return") or {}
        if yr.get("value") is not None:
            items.append((sym, yr["value"], yr.get("estimated"), yr.get("text") or ""))
    if not items:
        return _empty(title, "Needs at least one holding held for a year or more.")
    items.sort(key=lambda t: -t[1])
    pick = items[:n] + ([("…", None, False, "")] if len(items) > 2 * n else []) + \
        [t for t in items[-n:] if t not in items[:n]]
    rows = [{"label": s + (" est." if e else ""), "value": v, "cls": "fgood" if v >= 0 else "fbad", "title": f"{s}: {t}"}
            for s, v, e, t in pick if v is not None]
    sub = (f"Annualised return on the shares you hold, for stocks held a year or more ({len(items)} stocks). "
           "est. = some buy dates estimated, so the true figure is closer to zero.")
    table = (["Stock", "Return per year"], [[s, pct(v)] for s, v, _, _ in items])
    return _fig(title, sub, _hbar_svg(rows, diverging=True, label_w=120), table=table)


def tax_chart(run: dict, days: int = 90) -> str:
    title = f"Turning long-term in the next {days} days"
    by: dict[str, dict] = {}
    for l in run["tax"]["lots"]:
        dl = l.get("days_to_long_term")
        if dl is None or not 0 < dl <= days:
            continue
        e = by.setdefault(l["symbol"], {"symbol": l["symbol"], "date": l.get("long_term_from"), "qty": 0.0, "tax": 0.0, "days": dl})
        e["date"] = min(e["date"], l.get("long_term_from") or e["date"])
        e["days"] = min(e["days"], dl)
        e["qty"] += l["quantity"]
        e["tax"] += l.get("est_tax_if_sold") or 0.0
    if not by:
        return _empty(title, "No lots turn long-term in this window.")
    no_tax = sorted(e["symbol"] for e in by.values() if e["tax"] < 1)
    items = sorted((e for e in by.values() if e["tax"] >= 1), key=lambda e: e["date"])[:15]
    if not items:
        return _empty(title, f"{len(no_tax)} stocks turn long-term soon, but none has a taxable gain today.")
    rows = [{"label": f"{date.fromisoformat(e['date']).strftime('%d %b')} {e['symbol']}", "value": e["tax"], "cls": "f2",
             "title": f"{e['symbol']}: {e['qty']:g} shares turn long-term on {e['date']} (in {e['days']} days). "
                      f"Estimated tax if sold now: {inr(e['tax'], False)}"} for e in items]
    sub = ("Estimated tax if these lots are sold now (short-term). Waiting until the date moves them to long-term "
           "rates. Shown by the first date per stock.")
    if no_tax:
        sub += f" Not shown, no taxable gain today: {', '.join(no_tax[:8])}{' …' if len(no_tax) > 8 else ''}."
    table = (["Stock", "Long-term from", "Shares", "Tax if sold now"],
             [[e["symbol"], e["date"], f"{e['qty']:g}", inr(e["tax"], False)] for e in items])
    return _fig(title, sub, _hbar_svg(rows, fmt=lambda v: inr(v), label_w=150), table=table)


def portfolio_charts(conn, run: dict, thresholds: dict, as_of: date) -> dict[str, str]:
    return {"growth": growth_chart(conn, run, as_of), "allocation": allocation_chart(run, thresholds),
            "returns": returns_chart(run), "tax": tax_chart(run)}


# ---------------------------------------------------------------- per-stock charts
def business_chart(conn, symbol: str, as_of: date) -> str:
    d = Data(conn, as_of)
    rev = {p: v for p, v, _ in d.series(symbol, "revenue")}
    pat = {p: v for p, v, _ in d.series(symbol, "pat")}
    ebit = {p: v for p, v, _ in d.series(symbol, "ebit")}
    eq = {p: v for p, v, _ in d.series(symbol, "total_equity")}
    debt = {p: v for p, v, _ in d.series(symbol, "total_debt")}
    years = sorted(set(rev) | set(pat))[-10:]
    title = "Business trend"
    if len(years) < 2:
        return _empty(title, "Needs at least 2 years of confirmed company data (/research).")
    lab = [f"FY{p[2:4]}" for p in years]
    roce = [(ebit[p] / (eq[p] + debt.get(p, 0)) * 100) if p in ebit and p in eq and (eq[p] + debt.get(p, 0)) > 0 else None
            for p in years]
    crore = lambda v: f"₹{v:,.0f} cr"  # noqa: E731
    body = ("<div class='viz-grid2'>"
            f"<div><p class='viz-sub'>Revenue</p>{_columns_svg(lab, [rev.get(p) for p in years], crore)}</div>"
            f"<div><p class='viz-sub'>Profit (PAT)</p>{_columns_svg(lab, [pat.get(p) for p in years], crore)}</div>"
            f"<div><p class='viz-sub'>ROCE</p>{_columns_svg(lab, roce, lambda v: pct(v, False), cls='f3')}</div>"
            "</div>")
    table = (["Year", "Revenue (₹ cr)", "PAT (₹ cr)", "ROCE"],
             [[l_, f"{rev[p]:,.0f}" if p in rev else "–", f"{pat[p]:,.0f}" if p in pat else "–", pct(r, False)]
              for l_, p, r in zip(lab, years, roce)])
    return _fig(title, "Confirmed annual figures; red bars are losses. Hover a bar for its value.", body, table=table)


def pe_chart(conn, symbol: str, as_of: date) -> str:
    title = "P/E against its own history"
    d = Data(conn, as_of)
    pts = []
    for period, eps, pub in d.series(symbol, "eps"):
        px = d.price_on(symbol, pub)
        if px and eps > 0:
            pts.append((pub, px / eps))
    lp = d.last_price(symbol)
    eps_now = d.latest(symbol, "eps")
    cur = (lp[1], lp[0] / eps_now[1]) if lp and eps_now and eps_now[1] > 0 else None
    if cur:
        pts.append(cur)
    pts = sorted(set(pts))
    if len(pts) < 3:
        dates = d.closes(symbol)[0]
        return _empty(title, "Needs P/E at 3 or more dates: annual EPS (/research) and prices back to those filings"
                      + (f" (prices start {dates[0]})." if dates else "."))
    dates = [p[0] for p in pts]
    vals = [p[1] for p in pts]
    med = median(vals[:-1] if cur else vals)
    series = [{"name": "P/E", "short": "P/E", "cls": "s1", "values": vals},
              {"name": "Median", "short": "Median", "cls": "sm", "values": [med] * len(vals), "dash": True}]
    fmt = lambda v: f"{v:.1f}x"  # noqa: E731
    sub = (f"P/E on each annual results date and today. Today {vals[-1]:.1f}x vs median {med:.1f}x: "
           + ("above its usual level." if vals[-1] > med else "below its usual level."))
    table = (["Date", "P/E"], [[a, fmt(b)] for a, b in pts])
    return _fig(title, sub, _line_svg(dates, series, y_fmt=fmt, h=200), table=table)


def price_chart(conn, symbol: str, as_of: date) -> str:
    title = "Price, 200-day average and your trades"
    d = Data(conn, as_of)
    dates, closes, _ = d.closes(symbol)
    if len(dates) < 30:
        return _empty(title, "Needs daily prices (/sync).")
    sma = [None] * len(closes)
    run_sum = 0.0
    for i, c in enumerate(closes):
        run_sum += c
        if i >= 200:
            run_sum -= closes[i - 200]
        if i >= 199:
            sma[i] = run_sum / 200
    idx = list(range(len(dates) - 1, -1, -5))[::-1]  # weekly points
    wd = [dates[i] for i in idx]
    series = [{"name": "Price", "short": "Price", "cls": "s1", "values": [closes[i] for i in idx]},
              {"name": "200-day average", "short": "200-DMA", "cls": "s2", "values": [sma[i] for i in idx]}]
    trades = d.conn.execute("SELECT trade_date, side, SUM(quantity), SUM(quantity * price) FROM trade WHERE symbol = ?"
                            " AND trade_date >= ? GROUP BY trade_date, side ORDER BY trade_date", (symbol, wd[0])).fetchall()
    markers = []
    for td, side, q, amt in trades:
        i = min(bisect.bisect_left(wd, td), len(wd) - 1)
        markers.append({"i": i, "y": amt / q, "kind": "buy" if side == "BUY" else "sell",
                        "title": f"{'Bought' if side == 'BUY' else 'Sold'} {q:g} on {td} at ₹{amt / q:,.2f} ({inr(amt)})"})
    fmt = lambda v: f"₹{v:,.0f}"  # noqa: E731
    sub = ("Weekly closing price. Green triangles are your buys, red your sells (from imported trades). "
           "Below the 200-day average means a weak trend.")
    table = (["Date", "Side", "Avg price", "Amount"],
             [[t[0], t[1], f"₹{t[3] / t[2]:,.2f}", inr(t[3], False)] for t in trades]) if trades else None
    leg = [("Price", "bg1"), ("200-day average", "bg2")]
    if markers:
        leg += [("Buy", "dot bggood"), ("Sell", "dot bgbad")]
    return _fig(title, sub, _line_svg(wd, series, y_fmt=fmt, markers=markers, h=230), legend=leg, table=table)


def stock_charts(conn, symbol: str, as_of: date) -> dict[str, str]:
    return {"price": price_chart(conn, symbol, as_of), "business": business_chart(conn, symbol, as_of),
            "pe": pe_chart(conn, symbol, as_of)}


# ---------------------------------------------------------------- sell check
STATUS_ICON = {"good": "✓", "watch": "!", "bad": "✗", "unknown": "?"}
STATUS_LABEL = {"good": "OK", "watch": "Watch", "bad": "Concern", "unknown": "No data"}

SELL_CSS = """
.sell-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;margin:6px 0 10px}
.sell-tile{border:1px solid var(--grid);border-left-width:4px;border-radius:8px;padding:8px 10px}
.sell-tile.good{border-left-color:var(--good)}.sell-tile.watch{border-left-color:var(--warn)}
.sell-tile.bad{border-left-color:var(--bad)}.sell-tile.unknown{border-left-color:var(--muted)}
.sell-tile h4{margin:0;font-size:13px}.sell-tile .q{color:var(--ink2);font-size:11.5px;margin:0 0 4px}
.sell-st{font-weight:650;font-size:12.5px;white-space:nowrap}
.sell-st.good{color:var(--good)}.sell-st.watch{color:var(--ink2)}.sell-st.bad{color:var(--bad)}.sell-st.unknown{color:var(--muted)}
.sell-tile .h{font-size:12.5px;margin:2px 0}.sell-tile ul{margin:2px 0 0 16px;padding:0;font-size:12px;color:var(--ink2)}
.sell-verdict{font-weight:650;margin:2px 0 4px}
"""
CHART_CSS += SELL_CSS


def status_html(st: str) -> str:
    """Status never by colour alone: icon + word + colour."""
    return f"<span class='sell-st {escape(st)}'>{STATUS_ICON[st]} {STATUS_LABEL[st]}</span>"


def score_history_chart(hist: list[dict]) -> str:
    title = "Fundamentals and governance scores over 3 years"
    pts = [h for h in hist if h["fundamentals"] is not None or h["governance"] is not None]
    if len(pts) < 3:
        return _empty(title, "Needs company data over several quarters (/research).")
    dates = [h["date"] for h in pts]
    series = [{"name": "Fundamentals", "short": "Fund.", "cls": "s1", "values": [h["fundamentals"] for h in pts]},
              {"name": "Governance", "short": "Gov.", "cls": "s2", "values": [h["governance"] for h in pts]}]
    fmt = lambda v: f"{v:+.1f}"  # noqa: E731
    return _fig(title, "Engine scores from −2 to +2, recomputed at each quarter end with only the data public then. "
                "A falling line is the early warning.", _line_svg(dates, series, y_fmt=fmt, h=190, y_range=(-2, 2),
                                                                  zero_line=True),
                legend=[("Fundamentals", "bg1"), ("Governance", "bg2")],
                table=(["Quarter end", "Fundamentals", "Governance"],
                       [[h["date"], fmt(h["fundamentals"]) if h["fundamentals"] is not None else "–",
                         fmt(h["governance"]) if h["governance"] is not None else "–"] for h in pts]))


def relative_strength_chart(conn, symbol: str, as_of: date) -> str:
    title = f"Price vs {BENCHMARK}, last 12 months"
    d = Data(conn, as_of)
    dates, closes, _ = d.closes(symbol)
    bd, bc, _ = d.closes(BENCHMARK)
    if len(dates) < 60 or not bd:
        return _empty(title, "Needs a year of daily prices for the stock and the index (/sync).")
    start = (as_of - timedelta(days=365)).isoformat()
    i0 = bisect.bisect_left(dates, start)
    idx = list(range(len(dates) - 1, i0 - 1, -5))[::-1]
    wd = [dates[i] for i in idx]
    base_s = closes[idx[0]]
    bmap = lambda on: bc[max(bisect.bisect_right(bd, on) - 1, 0)]  # noqa: E731
    base_b = bmap(wd[0])
    s_vals = [closes[i] / base_s * 100 for i in idx]
    b_vals = [bmap(x) / base_b * 100 for x in wd]
    fmt = lambda v: f"{v:.0f}"  # noqa: E731
    gap = s_vals[-1] - b_vals[-1]
    sub = (f"Both start at 100. {symbol} is {abs(gap):.0f} points {'ahead of' if gap >= 0 else 'behind'} the index "
           "over the year.")
    return _fig(title, sub, _line_svg(wd, [{"name": symbol, "short": symbol[:10], "cls": "s1", "values": s_vals},
                                           {"name": BENCHMARK, "short": "NIFTY 500", "cls": "s2", "values": b_vals}],
                                      y_fmt=fmt, h=190),
                legend=[(symbol, "bg1"), (BENCHMARK, "bg2")],
                table=(["Week", symbol, BENCHMARK], [[a, fmt(b), fmt(c)] for a, b, c in zip(wd, s_vals, b_vals)][::-4][::-1]))


def promoter_chart(conn, symbol: str, as_of: date) -> str:
    title = "Promoter holding and pledge"
    d = Data(conn, as_of)
    prom = {p: v for p, v, _ in d.series(symbol, "promoter_pct")}
    pledge = {p: v for p, v, _ in d.series(symbol, "promoter_pledge_pct")}
    qs = sorted(set(prom) | set(pledge))[-8:]
    if len(qs) < 2:
        return _empty(title, "Needs shareholding patterns for 2 or more quarters (/research).")
    fmt = lambda v: f"{v:.1f}%"  # noqa: E731
    series = [{"name": "Promoter holding", "short": "Promoter", "cls": "s1", "values": [prom.get(q) for q in qs]},
              {"name": "Pledged (% of promoter shares)", "short": "Pledged", "cls": "s2", "values": [pledge.get(q) for q in qs]}]
    return _fig(title, "Quarterly shareholding. A falling holding or a rising pledge is a warning sign.",
                _line_svg(qs, series, y_fmt=fmt, h=190), legend=[("Promoter holding", "bg1"), ("Pledged", "bg2")],
                table=(["Quarter", "Promoter", "Pledged"], [[q, fmt(prom[q]) if q in prom else "–",
                                                            fmt(pledge[q]) if q in pledge else "–"] for q in qs]))


def sell_check_html(conn, check: dict, as_of: date, thresholds: dict, with_charts: bool = True) -> str:
    """Four tiles (status with icon + word), tax line, and one chart per measurable check."""
    from .sellcheck import score_history
    tiles = []
    for c in check["checks"]:
        lines = "".join(f"<li>{escape(x)}</li>" for x in c["lines"][:4])
        tiles.append(f"<div class='sell-tile {escape(c['status'])}'><h4>{escape(c['title'])} {status_html(c['status'])}</h4>"
                     f"<p class='q'>{escape(c['question'])}</p><p class='h'>{escape(c['headline'])}</p>"
                     f"{'<ul>' + lines + '</ul>' if lines else ''}</div>")
    t = check["tax"]
    tax = (f"Tax if sold now: {inr(t['tax_if_sold_now'], False)} on a gain of {inr(t['gain'], False)} ({t['lots']} lots)"
           + (f"; next lot turns long-term on {t['next_long_term']}" if t.get("next_long_term") else "") + ".")
    trig = ("<p class='viz-sub'>Engine triggers: " + escape("; ".join(check["triggers"])) + "</p>") if check["triggers"] else ""
    head = (f"<p class='sell-verdict'>{escape(check['summary']['verdict'])}</p>"
            f"<p class='viz-sub'>Label {escape(check['label'] or '–')} · {check['summary']['bad']} of 4 checks are concerns. "
            "The checks lay out evidence; the label comes from the engine, and the decision is yours.</p>" + trig)
    out = f"<div class='viz-fig'>{head}<div class='sell-grid'>{''.join(tiles)}</div><p class='viz-sub'>{escape(tax)}</p>"
    if with_charts:
        sym = check["symbol"]
        out += ("<div class='viz-grid2'>" + score_history_chart(score_history(conn, sym, as_of, thresholds)) +
                relative_strength_chart(conn, sym, as_of) + "</div>" + promoter_chart(conn, sym, as_of))
    return out + "</div>"


def sell_review_table(checks: list[dict]) -> str:
    """Report section: one row per stock worth a sell review."""
    if not checks:
        return "<p class='muted'>No holding needs a sell review today.</p>"
    head = ("<div class='viz-fig wrap'><table><tr><th>Stock</th><th>Label</th><th>Fundamentals</th><th>Trend</th>"
            "<th>Future</th><th>Team</th><th class='num'>Tax if sold now</th><th>Verdict</th></tr>")
    rows = []
    for c in checks:
        st = {x["key"]: x for x in c["checks"]}
        cells = "".join(f"<td title='{escape(st[k]['headline'])}'>{status_html(st[k]['status'])}</td>"
                        for k in ("fundamentals", "trend", "future", "team"))
        rows.append(f"<tr><td>{escape(c['symbol'])}</td><td class='lbl {escape(c['label'] or '')}'>{escape(c['label'] or '–')}</td>"
                    f"{cells}<td class='num'>{escape(inr(c['tax']['tax_if_sold_now'], False))}</td>"
                    f"<td>{escape(c['summary']['verdict'])}</td></tr>")
    return head + "".join(rows) + "</table></div>"
