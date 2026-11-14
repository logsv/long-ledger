"""Block (d): quality and governance. Red flags veto BUY/ACCUMULATE."""

from __future__ import annotations

from datetime import date, timedelta

from .base import BlockResult, Data, Evidence, cagr


def _year_ago(d: Data, symbol: str, metric: str):
    s = d.series(symbol, metric)
    if len(s) < 2:
        return None
    target = date.fromisoformat(s[-1][0]) - timedelta(days=330)
    older = [x for x in s if date.fromisoformat(x[0]) <= target]
    return older[-1] if older else None


def evaluate(d: Data, symbol: str, cfg: dict) -> BlockResult:
    g = cfg["governance"]
    b = BlockResult("governance", expected=7)
    ev = b.evidence

    pledge = d.latest(symbol, "promoter_pledge_pct")
    if pledge:
        v = pledge[1]
        pts = 1.0 if v == 0 else 0.0 if v <= 10 else -1.0 if v <= g["pledge_veto_pct"] else -2.0
        text = f"Promoter pledge {v:.1f}%"
        if v > g["pledge_veto_pct"]:
            b.veto.append(f"promoter pledge {v:.1f}% is above {g['pledge_veto_pct']:.0f}%")
        prev = _year_ago(d, symbol, "promoter_pledge_pct")
        if prev and v - prev[1] >= g["pledge_rise_veto_pts"]:
            pts = -2.0
            text += f", up {v - prev[1]:.1f} pts in a year"
            b.veto.append(f"promoter pledge rose {v - prev[1]:.1f} pts in a year")
        ev.append(Evidence("promoter_pledge_pct", v, pts, text, pledge[0]))

    prom = d.latest(symbol, "promoter_pct")
    if prom:
        prev = _year_ago(d, symbol, "promoter_pct")
        if prev:
            ch = prom[1] - prev[1]
            pts = 1.0 if ch >= 1 else -2.0 if ch <= -8 else -1.0 if ch <= -3 else 0.0
            ev.append(Evidence("promoter_change_1y", round(ch, 2), pts,
                               f"Promoter holding {prom[1]:.1f}% ({ch:+.1f} pts in a year)", prom[0]))
        else:
            ev.append(Evidence("promoter_pct", prom[1], None, f"Promoter holding {prom[1]:.1f}%", prom[0]))

    aq = d.latest(symbol, "auditor_qualified")
    if aq:
        if aq[1] >= 1:
            ev.append(Evidence("auditor_qualified", 1, -2.0, "Audit opinion is qualified", aq[0]))
            b.veto.append("qualified audit opinion")
        else:
            ev.append(Evidence("auditor_qualified", 0, 1.0, "Clean audit opinion", aq[0]))

    ar = d.series(symbol, "auditor_resigned")
    if ar:
        cutoff = (d.as_of - timedelta(days=730)).isoformat()
        recent = [x for x in ar if x[0] >= cutoff and x[1] >= 1]
        if recent:
            ev.append(Evidence("auditor_resigned", 1, -2.0, "Auditor resigned in the last 2 years", recent[-1][0]))
            b.veto.append("auditor resigned in the last 2 years")
        else:
            ev.append(Evidence("auditor_resigned", 0, 0.0, "No auditor resignation in the last 2 years", ar[-1][0]))

    rpt = d.latest(symbol, "rpt_pct_revenue")
    if rpt:
        v = rpt[1]
        pts = -2.0 if v > g["rpt_bad_pct"] else -1.0 if v > g["rpt_warn_pct"] else 1.0 if v <= 2 else 0.0
        ev.append(Evidence("rpt_pct_revenue", v, pts, f"Related-party transactions {v:.1f}% of revenue", rpt[0]))

    shares = d.latest(symbol, "shares_outstanding")
    old = d.value_years_back(symbol, "shares_outstanding", 3)
    if shares and old:
        span = (date.fromisoformat(shares[0]) - date.fromisoformat(old[0])).days / 365.25
        c = cagr(old[1], shares[1], span)
        if c is not None:
            w = g["dilution_cagr_warn"] * 100
            pts = 1.0 if c <= 0 else 0.0 if c <= w else -1.0 if c <= 2 * w else -2.0
            ev.append(Evidence("share_dilution_cagr", round(c, 2), pts,
                               f"Share count {c:+.1f}% a year over {span:.0f}y", shares[0]))

    fii, dii = d.latest(symbol, "fii_pct"), d.latest(symbol, "dii_pct")
    fii_old, dii_old = _year_ago(d, symbol, "fii_pct"), _year_ago(d, symbol, "dii_pct")
    if fii and dii and fii_old and dii_old:
        ch = (fii[1] + dii[1]) - (fii_old[1] + dii_old[1])
        pts = 1.0 if ch >= 2 else -1.0 if ch <= -2 else 0.0
        ev.append(Evidence("institutional_change_1y", round(ch, 2), pts,
                           f"FII+DII holding {fii[1] + dii[1]:.1f}% ({ch:+.1f} pts in a year)", fii[0]))
    return b
