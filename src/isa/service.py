"""High-level operations used by the CLI (and therefore by the slash commands)."""

from __future__ import annotations

import sqlite3
from datetime import date

from .config import Config
from .engine import scoring
from .portfolio import portfolio_view
from .tax import build_lots, tax_view


def universe(conn: sqlite3.Connection, view: dict) -> list[str]:
    held = [h["symbol"] for h in view["holdings"]]
    watch = [r[0] for r in conn.execute("SELECT symbol FROM watchlist ORDER BY symbol")]
    return held + [s for s in watch if s not in held]


def run(conn: sqlite3.Connection, cfg: Config, as_of: date | None = None,
        symbols: list[str] | None = None, record: bool = True) -> dict:
    """Portfolio view + a signal for every holding and watchlist stock."""
    as_of = as_of or date.today()
    book = build_lots(conn, cfg.tax)
    view = portfolio_view(conn, book, cfg.thresholds)
    held = {h["symbol"]: h for h in view["holdings"]}
    targets = symbols or universe(conn, view)
    signals = []
    for sym in targets:
        res = scoring.evaluate(conn, cfg, sym, as_of, position=held.get(sym))
        if record:
            res["signal_id"] = scoring.record(conn, res)
        signals.append(res)
    if record:
        conn.commit()
    prices = {h["symbol"]: h["price"] for h in view["holdings"] if h["price"]}
    taxes = tax_view(book, prices, as_of, cfg.tax, int(cfg.thresholds["tax_view"]["wait_window_days"]))
    pending = conn.execute("SELECT COUNT(*) FROM fundamental_fact WHERE confirmed = 0").fetchone()[0]
    return {"as_of": as_of.isoformat(), "portfolio": view, "signals": signals, "tax": taxes,
            "pending_facts": pending}


def summarize(signal: dict) -> dict:
    """Compact form for chat output."""
    return {
        "symbol": signal["symbol"], "label": signal["label"], "confidence": signal["confidence"],
        "composite": signal.get("composite"), "held": signal["held"],
        "why": signal.get("why"), "triggers": [f"{t['type']}: {t['detail']}" for t in signal.get("triggers", [])],
        "veto": signal.get("veto"), "timing": signal.get("timing"), "notes": signal.get("notes", []),
        "intrinsic_value": signal["blocks"]["valuation"].get("extra", {}).get("intrinsic_value"),
    }
