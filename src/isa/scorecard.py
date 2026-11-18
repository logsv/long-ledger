"""Long-investor scorecard: 12 metrics in 4 groups, plus your own return per year.

Everything here is read from data the engine already has. Broker-supplied
values come first: price is the broker's last price (or the latest daily
close), and average cost is the broker's average. Ratios are calculated from
confirmed company facts, because no broker feed supplies them. Colours reuse
the engine's own scoring bands, so a green cell always agrees with the label.
"""

from __future__ import annotations

from datetime import date

from .engine.base import Data, median
from .engine.valuation import _history, current_multiples

GROUPS = [
    ("Is it cheap?", ["pe", "pb", "dividend_yield", "price_vs_fair_value"]),
    ("Is it a good business?", ["roce", "roe", "cash_conversion"]),
    ("Is it growing?", ["revenue_cagr", "eps_cagr"]),
    ("Is it safe?", ["debt_to_equity", "interest_coverage", "promoter"]),
]
LABELS = {
    "pe": "P/E", "pb": "P/B", "dividend_yield": "Dividend yield", "price_vs_fair_value": "Price vs fair value",
    "roce": "ROCE", "roe": "ROE", "cash_conversion": "Cash conversion",
    "revenue_cagr": "Revenue growth/yr", "eps_cagr": "EPS growth/yr",
    "debt_to_equity": "Debt/equity", "interest_coverage": "Interest cover", "promoter": "Promoter (pledge)",
}


def _tone(points: float | None) -> str:
    if points is None:
        return "neutral"
    return "good" if points >= 1 else "bad" if points <= -1 else "ok"


def _ev(signal: dict, block: str, *keys: str) -> dict | None:
    for e in ((signal.get("blocks") or {}).get(block) or {}).get("evidence", []):
        if e["key"] in keys:
            return e
    return None


def xirr(flows: list[tuple[date, float]]) -> float | None:
    """Annualised return for dated cash flows (negative = money in). Bisection, no dependencies."""
    if len(flows) < 2 or not any(v < 0 for _, v in flows) or not any(v > 0 for _, v in flows):
        return None
    t0 = min(d for d, _ in flows)

    def npv(r: float) -> float:
        return sum(v / (1 + r) ** ((d - t0).days / 365.25) for d, v in flows)

    lo, hi = -0.9999, 10.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def own_return(lots: list[dict], symbol: str, price: float | None, as_of: date) -> dict:
    """Your annualised return on the shares you still hold (open lots, at the broker's cost)."""
    mine = [l for l in lots if l["symbol"] == symbol and l.get("cost_known", True) and l.get("cost")]
    if not mine or not price:
        return {"value": None, "estimated": False, "text": "no cost data"}
    flows, estimated, qty = [], False, 0.0
    for l in mine:
        d = l.get("acquired_before") if l.get("estimated") else l.get("buy_date")
        if not d:
            continue
        estimated |= bool(l.get("estimated"))
        flows.append((date.fromisoformat(d[:10]), -l["quantity"] * l["cost"]))
        qty += l["quantity"]
    if not flows:
        return {"value": None, "estimated": estimated, "text": "no buy dates"}
    first = min(d for d, _ in flows)
    cost = -sum(v for _, v in flows)
    if (as_of - first).days < 365:  # annualising a short holding exaggerates it
        simple = (qty * price / cost - 1) * 100 if cost > 0 else None
        months = max(1, round((as_of - first).days / 30.4))
        return {"value": None, "simple": None if simple is None else round(simple, 1), "estimated": estimated,
                "text": "not computable" if simple is None else
                f"{simple:+.1f}% in {months} months (under a year: not annualised)"}
    flows.append((as_of, qty * price))
    r = xirr(flows)
    if r is None:
        return {"value": None, "estimated": estimated, "text": "not computable"}
    note = " (est.: some shares were bought before this date, so the true yearly return is lower)" if estimated else ""
    return {"value": round(r * 100, 1), "estimated": estimated,
            "text": f"{r * 100:.1f}% a year since {first.isoformat()}{note}"}


def build(conn, signal: dict, as_of: date, lots: list[dict], cfg_valuation: dict | None = None) -> dict:
    """One stock's scorecard. Missing inputs show as None with a hint, never a guess."""
    sym = signal["symbol"]
    d = Data(conn, as_of)
    lp = d.last_price(sym)
    price = lp[0] if lp else None
    m: dict[str, dict] = {}

    def put(key, value, text, points=None, as_of_=None, fmt=None):
        m[key] = {"label": LABELS[key], "value": value, "text": text, "tone": _tone(points) if value is not None else "missing",
                  "as_of": as_of_, "fmt": fmt}

    # cheap?
    mult = current_multiples(d, sym, price) if price else {"pe": None, "pb": None, "ev_ebitda": None}
    years = int((cfg_valuation or {}).get("pe_history_years", 5))
    hist = _history(d, sym, years) if price else {"pe": [], "pb": []}
    for k in ("pe", "pb"):
        v = mult.get(k)
        med = median(hist.get(k) or [])
        pct = _ev(signal, "valuation", f"{k}_percentile")
        if v is None:
            put(k, None, "needs EPS, equity and shares (/research)" if k == "pe" else "needs equity and shares (/research)")
        else:
            vs = f" vs {med:.1f} median of its last {len(hist[k])} yearly filings" if med else " (no history yet)"
            put(k, round(v, 1), f"{v:.1f}{vs}", pct["points"] if pct else None, fmt="x")
    dps = d.latest(sym, "dividend_per_share")
    if dps and price:
        y = dps[1] / price * 100
        put("dividend_yield", round(y, 2), f"{y:.2f}% (₹{dps[1]:g} for FY to {dps[0]})",
            1.0 if y >= 2 else 0.0, dps[0], fmt="%")
    else:
        put("dividend_yield", None, "needs dividend per share (/research)")
    iv = ((signal.get("blocks") or {}).get("valuation") or {}).get("extra", {}).get("intrinsic_value") or {}
    e = _ev(signal, "valuation", "price_vs_intrinsic")
    if e and e["value"] is not None and "base" in iv:
        put("price_vs_fair_value", round((e["value"] - 1) * 100, 1),
            f"price {price:.0f} vs fair-value range {iv['low']:.0f}-{iv['high']:.0f}", e["points"], fmt="%±")
    else:
        put("price_vs_fair_value", None, iv.get("note") or "needs 3 years of cash flow (/research)")

    # good business?
    for key, block_key in (("roce", "roce"), ("roe", "roe")):
        e = _ev(signal, "fundamentals", block_key)
        put(key, e["value"] if e else None, e["text"] if e else "needs profit, equity and debt (/research)",
            e["points"] if e else None, e["as_of"] if e else None, "%")
    e = _ev(signal, "fundamentals", "cash_conversion")
    put("cash_conversion", e["value"] if e else None,
        (e["text"] + " (1.0 = all profit turned into cash)") if e else "needs 3 years of cash flow and profit (/research)",
        e["points"] if e else None, e["as_of"] if e else None, "x")

    # growing?
    for key, metric in (("revenue_cagr", "revenue"), ("eps_cagr", "eps")):
        e = _ev(signal, "fundamentals", f"{metric}_cagr_5y", f"{metric}_cagr_3y")
        put(key, e["value"] if e else None, e["text"] if e else "needs 3+ years of history (/research)",
            e["points"] if e else None, e["as_of"] if e else None, "%")

    # safe?
    for key in ("debt_to_equity", "interest_coverage"):
        e = _ev(signal, "fundamentals", key)
        val = e["value"] if e else None
        if e and val is None and e["points"] is not None and e["points"] > 0:
            val = 0.0  # "no finance costs"
        put(key, val, e["text"] if e else "needs debt, equity and interest (/research)",
            e["points"] if e else None, e["as_of"] if e else None, "x")
    prom, pledge = _ev(signal, "governance", "promoter_pct"), _ev(signal, "governance", "promoter_pledge_pct")
    if prom or pledge:
        pv = d.latest(sym, "promoter_pct")
        text = (f"{pv[1]:.1f}% held" if pv else "holding n/a") + (f", {pledge['value']:.1f}% pledged" if pledge else "")
        ch = _ev(signal, "governance", "promoter_change_1y")
        if ch:
            text += f" ({ch['value']:+.1f} pts in 1y)"
        put("promoter", pv[1] if pv else None, text, pledge["points"] if pledge else (ch["points"] if ch else None),
            pv[0] if pv else None, "%")
    else:
        put("promoter", None, "needs a shareholding pattern (/research)")

    sh = d.latest(sym, "shares_outstanding")
    mcap = round(price * sh[1], 0) if price and sh else None
    filled = sum(1 for v in m.values() if v["value"] is not None)
    return {
        "symbol": sym, "price": price, "price_date": lp[1] if lp else None,
        "market_cap_cr": mcap, "your_return": own_return(lots, sym, price, as_of),
        "groups": [{"title": t, "metrics": [{"key": k, **m[k]} for k in keys]} for t, keys in GROUPS],
        "filled": filled, "of": len(m),
    }


def build_all(conn, signals: list[dict], as_of: date, lots: list[dict], cfg_valuation: dict | None = None) -> dict:
    return {s["symbol"]: build(conn, s, as_of, lots, cfg_valuation)
            for s in signals if s.get("label") != "ETF"}
