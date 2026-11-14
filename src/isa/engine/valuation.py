"""Block (e): valuation vs own history and peers, plus an intrinsic value range."""

from __future__ import annotations

from datetime import date, timedelta

from .base import BlockResult, Data, Evidence, median, percentile_rank

PCT_CUTS = ((20, 2.0), (40, 1.0), (60, 0.0), (80, -1.0))


def _pct_points(p: float) -> float:
    for limit, pts in PCT_CUTS:
        if p <= limit:
            return pts
    return -2.0


def _annual(d: Data, symbol: str, metric: str) -> dict[str, tuple[float, str]]:
    return {p: (v, pub) for p, v, pub in d.series(symbol, metric)}


def current_multiples(d: Data, symbol: str, price: float) -> dict[str, float | None]:
    out: dict[str, float | None] = {"pe": None, "pb": None, "ev_ebitda": None}
    eps = d.latest(symbol, "eps")
    if eps and eps[1] > 0:
        out["pe"] = price / eps[1]
    eq, sh = d.latest(symbol, "total_equity"), d.latest(symbol, "shares_outstanding")
    if eq and sh and sh[1] > 0 and eq[1] > 0:
        out["pb"] = price / (eq[1] / sh[1])
    ebitda, debt, cash = d.latest(symbol, "ebitda"), d.latest(symbol, "total_debt"), d.latest(symbol, "cash")
    if ebitda and sh and ebitda[1] > 0:
        ev_ = price * sh[1] + (debt[1] if debt else 0.0) - (cash[1] if cash else 0.0)
        out["ev_ebitda"] = ev_ / ebitda[1]
    return out


def _history(d: Data, symbol: str, years: int) -> dict[str, list[float]]:
    """Multiples at each past annual filing date, using the price that day."""
    hist: dict[str, list[float]] = {"pe": [], "pb": [], "ev_ebitda": []}
    cutoff = (d.as_of - timedelta(days=int(365.25 * years))).isoformat()
    eps, eq, sh = _annual(d, symbol, "eps"), _annual(d, symbol, "total_equity"), _annual(d, symbol, "shares_outstanding")
    ebitda, debt, cash = _annual(d, symbol, "ebitda"), _annual(d, symbol, "total_debt"), _annual(d, symbol, "cash")
    for period, (e, pub) in eps.items():
        if pub < cutoff:
            continue
        px = d.price_on(symbol, pub)
        if not px:
            continue
        if e > 0:
            hist["pe"].append(px / e)
        if period in eq and period in sh and sh[period][0] > 0 and eq[period][0] > 0:
            hist["pb"].append(px / (eq[period][0] / sh[period][0]))
        if period in ebitda and period in sh and ebitda[period][0] > 0:
            ev_ = px * sh[period][0] + debt.get(period, (0.0,))[0] - cash.get(period, (0.0,))[0]
            hist["ev_ebitda"].append(ev_ / ebitda[period][0])
    return hist


def _peers(d: Data, symbol: str) -> list[str]:
    r = d.conn.execute("SELECT industry, sector FROM security WHERE symbol = ?", (symbol,)).fetchone()
    if not r:
        return []
    col, val = ("industry", r["industry"]) if r["industry"] else ("sector", r["sector"])
    if not val:
        return []
    return [x[0] for x in d.conn.execute(
        f"SELECT symbol FROM security WHERE {col} = ? AND symbol != ? AND is_index = 0", (val, symbol))]


def intrinsic_range(d: Data, symbol: str, cfg: dict) -> dict | None:
    """2-stage DCF on average free cash flow per share (last 3 years)."""
    cfo, capex = _annual(d, symbol, "cfo"), _annual(d, symbol, "capex")
    sh = d.latest(symbol, "shares_outstanding")
    years = sorted(set(cfo) & set(capex))[-3:]
    if len(years) < 3 or not sh or sh[1] <= 0:
        return None
    fcf_ps = sum(cfo[p][0] - capex[p][0] for p in years) / len(years) / sh[1]
    if fcf_ps <= 0:
        return {"fcf_per_share": round(fcf_ps, 2), "note": "average free cash flow is negative: DCF not meaningful"}
    rev = d.series(symbol, "revenue")
    growth = None
    for n in (5, 3):
        old = d.value_years_back(symbol, "revenue", n)
        if old and rev and old[1] > 0 and rev[-1][1] > 0:
            span = (date.fromisoformat(rev[-1][0]) - date.fromisoformat(old[0])).days / 365.25
            growth = (rev[-1][1] / old[1]) ** (1 / span) - 1
            break
    if growth is None:
        return None
    r, tg, n = cfg["discount_rate"], cfg["terminal_growth"], int(cfg["stage1_years"])
    g = max(0.0, min(growth, cfg["max_growth"]))

    def dcf(g_: float, r_: float) -> float:
        r_ = max(r_, tg + 0.01)
        value, f = 0.0, fcf_ps
        for t in range(1, n + 1):
            f *= 1 + g_
            value += f / (1 + r_) ** t
        terminal = f * (1 + tg) / (r_ - tg)
        return value + terminal / (1 + r_) ** n

    return {
        "fcf_per_share": round(fcf_ps, 2),
        "low": round(dcf(g * cfg["growth_low_factor"], r + 0.01), 2),
        "base": round(dcf(g, r), 2),
        "high": round(dcf(min(g * cfg["growth_high_factor"], cfg["max_growth"]), r - 0.01), 2),
        "assumptions": {"growth_used": round(g, 4), "revenue_cagr": round(growth, 4),
                        "discount_rate": r, "terminal_growth": tg, "stage1_years": n,
                        "fcf_years": years},
    }


def evaluate(d: Data, symbol: str, cfg: dict) -> BlockResult:
    b = BlockResult("valuation", expected=5)
    lp = d.last_price(symbol)
    if not lp:
        return b
    price, price_date = lp
    cur = current_multiples(d, symbol, price)
    hist = _history(d, symbol, int(cfg["pe_history_years"]))
    names = {"pe": "P/E", "pb": "P/B", "ev_ebitda": "EV/EBITDA"}
    for k in ("pe", "pb", "ev_ebitda"):
        v = cur[k]
        if v is None:
            if k == "pe" and d.latest(symbol, "eps"):
                b.evidence.append(Evidence("pe", None, -1.0, "P/E not meaningful: EPS is zero or negative", price_date))
            continue
        if len(hist[k]) >= 3:
            p = percentile_rank(v, hist[k])
            b.evidence.append(Evidence(f"{k}_percentile", round(p, 1), _pct_points(p),
                                       f"{names[k]} {v:.1f} is at the {p:.0f}th percentile of its"
                                       f" {len(hist[k])}-year history", price_date))
        else:
            b.evidence.append(Evidence(k, round(v, 2), None, f"{names[k]} {v:.1f} (not enough history)", price_date))

    if cur["pe"]:
        peer_pes = []
        for peer in _peers(d, symbol):
            pl = d.last_price(peer)
            if pl:
                pe = current_multiples(d, peer, pl[0])["pe"]
                if pe:
                    peer_pes.append(pe)
        if len(peer_pes) >= 2:
            m = median(peer_pes)
            ratio = cur["pe"] / m
            pts = 1.0 if ratio < 0.8 else -1.0 if ratio > 1.25 else 0.0
            b.evidence.append(Evidence("pe_vs_peers", round(ratio, 2), pts,
                                       f"P/E {cur['pe']:.1f} vs peer median {m:.1f} ({len(peer_pes)} peers)",
                                       price_date))
        eps_g = None
        for n in (5, 3):
            old = d.value_years_back(symbol, "eps", n)
            latest = d.latest(symbol, "eps")
            if old and latest and old[1] > 0 and latest[1] > 0:
                span = (date.fromisoformat(latest[0]) - date.fromisoformat(old[0])).days / 365.25
                eps_g = ((latest[1] / old[1]) ** (1 / span) - 1) * 100
                break
        if eps_g and eps_g > 0:
            peg = cur["pe"] / eps_g
            pts = 1.0 if peg < 1 else -1.0 if peg > 2 else 0.0
            b.evidence.append(Evidence("peg", round(peg, 2), pts, f"PEG {peg:.2f} (EPS growth {eps_g:.1f}%)", price_date))

    iv = intrinsic_range(d, symbol, cfg)
    if iv:
        b.extra["intrinsic_value"] = iv
        if "base" in iv:
            lo, base, hi = iv["low"], iv["base"], iv["high"]
            pts = 2.0 if price < lo else 1.0 if price < base else 0.0 if price <= hi else -1.0 if price <= hi * 1.3 else -2.0
            b.evidence.append(Evidence("price_vs_intrinsic", round(price / base, 3), pts,
                                       f"Price {price:.1f} vs intrinsic range {lo:.0f}-{hi:.0f} (base {base:.0f})",
                                       price_date))
        else:
            b.evidence.append(Evidence("price_vs_intrinsic", None, None, iv["note"], price_date))
    b.extra["price"] = price
    b.extra["price_date"] = price_date
    b.extra["multiples"] = {k: (round(v, 2) if v else None) for k, v in cur.items()}
    return b
