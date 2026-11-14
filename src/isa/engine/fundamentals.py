"""Block (c): fundamentals from annual financials."""

from __future__ import annotations

from datetime import date

from .base import BlockResult, Data, Evidence, band, cagr

GROWTH_CUTS = [(15, 2), (10, 1), (5, 0), (0, -1)]


def _growth(d: Data, symbol: str, metric: str, label: str) -> Evidence | None:
    latest = d.latest(symbol, metric)
    if not latest:
        return None
    for years in (5, 3):
        old = d.value_years_back(symbol, metric, years)
        if not old:
            continue
        span = (date.fromisoformat(latest[0]) - date.fromisoformat(old[0])).days / 365.25
        g = cagr(old[1], latest[1], span)
        key = f"{metric}_cagr_{years}y"
        if g is None:
            if latest[1] <= 0:
                return Evidence(key, None, -2.0, f"{label} is zero or negative in the latest year", latest[0])
            return Evidence(key, None, None,
                            f"{label} turned positive from a loss {years}y ago: growth rate not meaningful",
                            latest[0])
        return Evidence(key, round(g, 2), band(g, GROWTH_CUTS),
                        f"{label} {years}y CAGR {g:.1f}%", latest[0])
    return None


def evaluate(d: Data, symbol: str) -> BlockResult:
    b = BlockResult("fundamentals", expected=12)
    ev = b.evidence

    for metric, label in (("revenue", "Revenue"), ("pat", "Profit"), ("eps", "EPS")):
        e = _growth(d, symbol, metric, label)
        if e:
            ev.append(e)

    pat = d.latest(symbol, "pat")
    eq_series = d.series(symbol, "total_equity")
    if pat and eq_series:
        eq_now = eq_series[-1][1]
        eq_prev = eq_series[-2][1] if len(eq_series) > 1 else eq_now
        avg_eq = (eq_now + eq_prev) / 2
        if avg_eq > 0:
            roe = pat[1] / avg_eq * 100
            ev.append(Evidence("roe", round(roe, 2), band(roe, [(20, 2), (15, 1), (10, 0), (5, -1)]),
                               f"ROE {roe:.1f}%", pat[0]))
        else:
            ev.append(Evidence("roe", None, -2.0, "Negative shareholders' equity", pat[0]))

    ebit = d.latest(symbol, "ebit")
    equity = d.latest(symbol, "total_equity")
    debt = d.latest(symbol, "total_debt")
    if ebit and equity:
        ce = equity[1] + (debt[1] if debt else 0.0)
        if ce > 0:
            roce = ebit[1] / ce * 100
            ev.append(Evidence("roce", round(roce, 2), band(roce, [(20, 2), (15, 1), (10, 0), (6, -1)]),
                               f"ROCE {roce:.1f}%", ebit[0]))

    ebitda_s = {p: v for p, v, _ in d.series(symbol, "ebitda")}
    rev_s = {p: v for p, v, _ in d.series(symbol, "revenue")}
    margins = [(p, ebitda_s[p] / rev_s[p] * 100) for p in sorted(ebitda_s) if p in rev_s and rev_s[p] > 0]
    if len(margins) >= 2:
        now = margins[-1][1]
        prior = [m for _, m in margins[-4:-1]]
        avg = sum(prior) / len(prior)
        delta = round(now - avg, 6)
        pts = 1.0 if delta >= 2 else (-1.0 if delta <= -2 else 0.0)
        ev.append(Evidence("ebitda_margin", round(now, 2), pts,
                           f"EBITDA margin {now:.1f}% vs {avg:.1f}% earlier ({delta:+.1f} pts)", margins[-1][0]))

    if equity and equity[1] > 0:
        de = (debt[1] if debt else 0.0) / equity[1]
        pts = 2.0 if de <= 0.1 else 1.0 if de <= 0.5 else 0.0 if de <= 1 else -1.0 if de <= 2 else -2.0
        ev.append(Evidence("debt_to_equity", round(de, 2), pts, f"Debt/equity {de:.2f}", equity[0]))

    interest = d.latest(symbol, "interest_expense")
    if ebit and interest:
        if interest[1] <= 0:
            ev.append(Evidence("interest_coverage", None, 2.0, "No finance costs", ebit[0]))
        else:
            ic = ebit[1] / interest[1]
            ev.append(Evidence("interest_coverage", round(ic, 2),
                               band(ic, [(10, 2), (5, 1), (3, 0), (1.5, -1)]),
                               f"Interest coverage {ic:.1f}x", ebit[0]))

    cfo_s = {p: v for p, v, _ in d.series(symbol, "cfo")}
    pat_s = {p: v for p, v, _ in d.series(symbol, "pat")}
    common = sorted(set(cfo_s) & set(pat_s))[-5:]
    if len(common) >= 3:
        pat_sum = sum(pat_s[p] for p in common)
        if pat_sum > 0:
            cc = sum(cfo_s[p] for p in common) / pat_sum
            ev.append(Evidence("cash_conversion", round(cc, 2),
                               band(cc, [(1.0, 2), (0.8, 1), (0.6, 0), (0.3, -1)]),
                               f"Cash conversion (CFO/PAT, {len(common)}y) {cc:.2f}", common[-1]))

    capex_s = {p: v for p, v, _ in d.series(symbol, "capex")}
    fcf_years = sorted(set(cfo_s) & set(capex_s))[-5:]
    if len(fcf_years) >= 3:
        positive = sum(1 for p in fcf_years if cfo_s[p] - capex_s[p] > 0)
        ratio = positive / len(fcf_years)
        ev.append(Evidence("fcf_positive_years", positive,
                           band(ratio, [(1.0, 2), (0.8, 1), (0.6, 0), (0.4, -1)]),
                           f"Free cash flow positive in {positive} of {len(fcf_years)} years", fcf_years[-1]))

    wc = {}
    for m in ("receivable_days", "inventory_days", "payable_days"):
        for p, v, _ in d.series(symbol, m):
            wc.setdefault(p, {})[m] = v
    wc_full = sorted((p, x["receivable_days"] + x["inventory_days"] - x["payable_days"])
                     for p, x in wc.items() if len(x) == 3)
    if len(wc_full) >= 2:
        now_p, now_v = wc_full[-1]
        old_v = wc_full[max(0, len(wc_full) - 4)][1]
        delta = now_v - old_v
        pts = 1.0 if delta <= -10 else (-1.0 if delta >= 15 else 0.0)
        ev.append(Evidence("working_capital_days", round(now_v, 1), pts,
                           f"Working capital cycle {now_v:.0f} days ({delta:+.0f} vs earlier)", now_p))

    dps = d.latest(symbol, "dividend_per_share")
    shares = d.latest(symbol, "shares_outstanding")
    if dps and shares and pat and pat[1] > 0:
        payout = dps[1] * shares[1] / pat[1] * 100
        pts = 1.0 if 0 < payout <= 80 else 0.0
        ev.append(Evidence("dividend_payout", round(payout, 1), pts, f"Dividend payout {payout:.0f}%", dps[0]))

    return b
