"""Risk flags from price and position data. Flags are prompts to review,
never buy/sell signals: those need company analysis."""

from __future__ import annotations

from .base import Data


def flags(d: Data, symbol: str, tech: dict, cfg: dict, position: dict | None) -> list[dict]:
    mon, st = cfg["monitor"], cfg["sell_triggers"]
    out: list[dict] = []
    if not tech.get("available"):
        return out
    rs = tech.get("relative_strength_6m")
    dma200 = tech.get("dma200")
    if dma200 and tech["price"] < dma200 and rs is not None and rs <= mon["weak_rs_flag"]:
        out.append({"type": "weak_trend", "detail": f"below 200-DMA and trailing the index by {abs(rs):.0%} over 6 months"})
    dd = tech.get("drawdown_from_52w_high")
    if dd is not None and dd <= -mon["drawdown_flag"]:
        out.append({"type": "deep_drawdown", "detail": f"{dd:.0%} from its 52-week high"})
    vr = tech.get("volume_ratio_20_100")
    if vr is not None and vr >= mon["volume_spike"]:
        out.append({"type": "volume_spike", "detail": f"20-day volume {vr:.1f}x normal: check news"})
    if position:
        pnl = position.get("unrealised_pct")
        if pnl is not None and pnl <= -st["loss_threshold"]:
            out.append({"type": "loss_from_cost", "detail": f"{pnl:.0%} from your average cost"})
    return out
