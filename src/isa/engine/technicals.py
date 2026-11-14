"""Block (f): technicals for TIMING only. Never changes the label."""

from __future__ import annotations

from .base import Data


def _sma(xs: list[float], n: int) -> float | None:
    return sum(xs[-n:]) / n if len(xs) >= n else None


def _ret(xs: list[float], n: int) -> float | None:
    return xs[-1] / xs[-1 - n] - 1 if len(xs) > n and xs[-1 - n] > 0 else None


def evaluate(d: Data, symbol: str, cfg: dict) -> dict:
    t = cfg["technicals"]
    dates, closes, vols = d.closes(symbol)
    out: dict = {"available": len(closes) >= 50, "observations": []}
    if not out["available"]:
        out["advice"] = "not enough price history for timing (need 50+ days)"
        return out
    price = closes[-1]
    dma50, dma200 = _sma(closes, 50), _sma(closes, 200)
    out.update(price=price, date=dates[-1], dma50=dma50, dma200=dma200)
    obs = out["observations"]
    obs.append(f"Price {'above' if price > dma50 else 'below'} 50-DMA ({dma50:.1f})")
    if dma200:
        obs.append(f"Price {'above' if price > dma200 else 'below'} 200-DMA ({dma200:.1f})")
    window = closes[-252:]
    high = max(window)
    out["drawdown_from_52w_high"] = price / high - 1
    obs.append(f"{out['drawdown_from_52w_high']:.0%} from 52-week high ({high:.1f})")
    rs = None
    _, idx, _ = d.closes(t["index_symbol"])
    r_stock = _ret(closes, 126)
    r_index = _ret(idx, 126) if idx else None
    if r_stock is not None and r_index is not None:
        rs = r_stock - r_index
        out["relative_strength_6m"] = rs
        obs.append(f"6-month return {r_stock:+.0%} vs {t['index_symbol']} {r_index:+.0%}")
    v = [x for x in vols if x]
    if len(v) >= 100:
        out["volume_ratio_20_100"] = (sum(v[-20:]) / 20) / (sum(v[-100:]) / 100)
        obs.append(f"20-day volume {out['volume_ratio_20_100']:.1f}x the 100-day average")
    if len(closes) >= 20:
        out["support_20d"] = min(closes[-20:])
        out["resistance_20d"] = max(closes[-20:])

    weak = (dma200 is not None and price < dma200) or (rs is not None and rs < 0)
    strong = dma200 is not None and price > dma50 > dma200 and (rs is None or rs >= 0)
    if weak:
        out["advice"] = (f"trend weak: if buying, stagger entry over {t['stagger_tranches']} tranches")
        out["stance"] = "weak"
    elif strong:
        out["advice"] = "trend supportive: normal entry"
        out["stance"] = "strong"
    else:
        out["advice"] = "trend neutral"
        out["stance"] = "neutral"
    return out
