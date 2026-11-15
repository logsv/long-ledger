"""Block (a): market regime from broker index data (Kite): index trend, India VIX,
breadth of your holdings, and sector-index rotation.

The macro block never creates a label on its own: scoring only uses it when at
least one company block (fundamentals, governance, valuation) has data.
"""

from __future__ import annotations

from .base import BlockResult, Data, Evidence, percentile_rank


def _sma(xs: list[float], n: int) -> float | None:
    return sum(xs[-n:]) / n if len(xs) >= n else None


def _ret(xs: list[float], n: int) -> float | None:
    return xs[-1] / xs[-1 - n] - 1 if len(xs) > n and xs[-1 - n] > 0 else None


def evaluate(d: Data, cfg: dict, breadth_symbols: list[str]) -> tuple[BlockResult, dict]:
    m = cfg["market"]
    b = BlockResult("macro", expected=4)
    info: dict = {"indices": {}, "sectors": [], "missing": []}

    _, broad, _ = d.closes(m["broad_index"])
    if len(broad) >= 200:
        px, d50, d200 = broad[-1], _sma(broad, 50), _sma(broad, 200)
        b.evidence.append(Evidence("broad_vs_200dma", round(px / d200 - 1, 4), 1.0 if px > d200 else -1.0,
                                   f"{m['broad_index']} {px:,.0f} is {px / d200 - 1:+.1%} vs its 200-DMA"))
        b.evidence.append(Evidence("broad_50_vs_200", round(d50 / d200 - 1, 4), 1.0 if d50 > d200 else -1.0,
                                   f"{m['broad_index']} 50-DMA {'above' if d50 > d200 else 'below'} 200-DMA"))
        info["indices"][m["broad_index"]] = {"close": px, "dma50": d50, "dma200": d200,
                                             "ret_3m": _ret(broad, 63), "ret_6m": _ret(broad, 126)}
    else:
        info["missing"].append(f"{m['broad_index']} (need 200+ days)")

    _, large, _ = d.closes(m["large_cap_index"])
    if len(large) >= 200:
        px, d200 = large[-1], _sma(large, 200)
        b.evidence.append(Evidence("large_vs_200dma", round(px / d200 - 1, 4), None,
                                   f"{m['large_cap_index']} {px:,.0f} is {px / d200 - 1:+.1%} vs its 200-DMA"))
        info["indices"][m["large_cap_index"]] = {"close": px, "dma200": d200, "ret_6m": _ret(large, 126)}
    else:
        info["missing"].append(m["large_cap_index"])

    _, vix, _ = d.closes(m["volatility_index"])
    if len(vix) >= 60:
        window = vix[-int(m["vix_lookback_days"] * 250 / 365):]
        p = percentile_rank(vix[-1], window)
        pts = 1.0 if p <= 30 else -1.0 if p >= 80 else 0.0
        b.evidence.append(Evidence("vix_percentile", round(p, 1), pts,
                                   f"India VIX {vix[-1]:.1f} at the {p:.0f}th percentile of the last year"))
        info["indices"][m["volatility_index"]] = {"close": vix[-1], "percentile_1y": p}
    else:
        info["missing"].append(m["volatility_index"])

    above, counted = 0, 0
    for sym in breadth_symbols:
        _, closes, _ = d.closes(sym)
        if len(closes) >= 200:
            counted += 1
            above += closes[-1] > _sma(closes, 200)
    if counted >= 5:
        share = above / counted * 100
        pts = 1.0 if share >= 60 else -1.0 if share <= 40 else 0.0
        b.evidence.append(Evidence("holdings_breadth", round(share, 1), pts,
                                   f"{above} of {counted} of your stocks are above their 200-DMA ({share:.0f}%)"))
    info["breadth"] = {"above_200dma": above, "counted": counted}

    for name in m["sector_indices"]:
        _, s, _ = d.closes(name)
        r3, r6 = _ret(s, 63), _ret(s, 126)
        if r3 is not None:
            info["sectors"].append({"index": name, "ret_3m": r3, "ret_6m": r6})
    info["sectors"].sort(key=lambda x: -x["ret_3m"])

    score = b.score
    has_index = any(e.key in ("broad_vs_200dma", "vix_percentile") for e in b.evidence)
    info["regime"] = ("unknown: import NIFTY 500 / INDIA VIX prices with /sync" if score is None or not has_index else
                      "risk-on" if score >= 0.5 else "risk-off" if score <= -0.5 else "neutral")
    info["block"] = b.to_dict()
    return b, info
