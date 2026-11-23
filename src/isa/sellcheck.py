"""Sell check: four questions a long-term holder asks before selling, side by side.

  1. Fundamentals  is the business getting worse?        fundamentals score now vs a year ago (point-in-time)
  2. Trend         is the market telling me something?   200-day average, relative strength, drawdown
  3. Future        is the reason I bought still true?    thesis conditions, recent news
  4. Team          can I trust the people running it?    governance score: pledge, promoter, auditor, RPT, dilution

Each check is "good", "watch" or "bad" from fixed rules on the engine's own numbers. The check
never changes the engine's label; it lays out the evidence so the user decides. A missing input
is "unknown", never a guess.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from .config import ROOT
from .engine import fundamentals, governance
from .engine.base import Data
from .engine.scoring import _check_thesis

STATUS_TEXT = {"good": "OK", "watch": "Watch", "bad": "Concern", "unknown": "No data"}


def _metrics(conn, signal: dict, as_of: date) -> dict[str, float]:
    """Same inputs thesis conditions use: latest facts plus every evidence value."""
    from .importers.facts import METRICS
    d = Data(conn, as_of)
    out: dict[str, float] = {}
    for m in METRICS:
        v = d.latest(signal["symbol"], m)
        if v:
            out[m] = v[1]
    for b in (signal.get("blocks") or {}).values():
        for e in b.get("evidence", []):
            if e.get("value") is not None:
                out[e["key"]] = e["value"]
    return out


def score_history(conn, symbol: str, as_of: date, thresholds: dict, quarters: int = 12) -> list[dict]:
    """Fundamentals and governance scores recomputed at past quarter ends (point-in-time: only
    facts published by each date are used)."""
    out = []
    for q in range(quarters, -1, -1):
        on = as_of - timedelta(days=91 * q)
        d = Data(conn, on)
        f, g = fundamentals.evaluate(d, symbol), governance.evaluate(d, symbol, thresholds)
        out.append({"date": on.isoformat(), "fundamentals": f.score, "governance": g.score})
    return out


def _news(symbol: str) -> list[dict]:
    files = sorted((ROOT / "data" / "imports" / "research").glob(f"{symbol}-news-*.json"))
    if not files:
        return []
    try:
        items = json.loads(Path(files[-1]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [i for i in items if isinstance(i, dict)][:8] if isinstance(items, list) else []


def check(conn, cfg, signal: dict, as_of: date, lots: list[dict] | None = None) -> dict:
    """The four checks for one stock. `lots` are the tax view's open lots (all stocks; filtered here)."""
    sym = signal["symbol"]
    blocks = signal.get("blocks") or {}
    out: dict = {"symbol": sym, "label": signal.get("label"), "confidence": signal.get("confidence"),
                 "triggers": [f"{t['type']}: {t['detail']}" for t in signal.get("triggers", [])], "checks": []}

    # 1. fundamentals: level and direction over a year
    hist = score_history(conn, sym, as_of, cfg.thresholds, quarters=4)
    now, year_ago = hist[-1]["fundamentals"], hist[0]["fundamentals"]
    lines = [e["text"] for e in (blocks.get("fundamentals") or {}).get("evidence", []) if (e.get("points") or 0) < 0][:3]
    if now is None:
        st, head = "unknown", "No confirmed company data (/research)"
    else:
        fell = year_ago is not None and now - year_ago <= -1.0
        st = "bad" if now <= -0.5 or fell else "good" if now >= 0.5 and not (year_ago is not None and now < year_ago - 0.5) else "watch"
        head = f"Score {now:+.1f}" + (f", a year ago {year_ago:+.1f}" if year_ago is not None else "")
    out["checks"].append({"key": "fundamentals", "title": "Fundamentals", "question": "Is the business getting worse?",
                          "status": st, "headline": head, "lines": lines})

    # 2. trend
    t = signal.get("technicals") or {}
    if not t.get("available"):
        st, head, lines = "unknown", "Not enough price history", []
    else:
        below = t.get("dma200") is not None and t["price"] < t["dma200"]
        rs = t.get("relative_strength_6m")
        dd = t.get("drawdown_from_52w_high") or 0
        lag = rs is not None and rs <= -0.10
        st = "bad" if (below and lag) or dd <= -0.35 else "watch" if below or lag or dd <= -0.25 else "good"
        head = (("Below" if below else "Above") + " its 200-day average"
                + (f"; {rs * 100:+.0f} pts vs NIFTY 500 over 6 months" if rs is not None else ""))
        lines = [o for o in t.get("observations", []) if "52-week" in o or "6-month" in o]
    out["checks"].append({"key": "trend", "title": "Trend", "question": "Is the market telling me something?",
                          "status": st, "headline": head, "lines": lines})

    # 3. future: thesis conditions + news
    conds = _check_thesis(conn, sym, _metrics(conn, signal, as_of))
    news = _news(sym)
    if not conds:
        st, head = "unknown", "No thesis written: add 2-3 measurable conditions with /thesis"
    else:
        broken = [c for c in conds if c["status"] == "broken"]
        unknown = [c for c in conds if c["status"] == "unknown"]
        st = "bad" if broken else "watch" if unknown else "good"
        head = (f"{len(broken)} of {len(conds)} thesis conditions broken" if broken else
                f"{len(conds) - len(unknown)} of {len(conds)} conditions hold" + (f", {len(unknown)} unknown" if unknown else ""))
    lines = [f"{c['metric']} {c['op']} {c['threshold']:g}: {c['status']}"
             + (f" (now {c['value']:g})" if c["value"] is not None else "") for c in conds]
    lines += [f"{n.get('date', '')}: {n.get('headline', '')}" for n in news[:3]]
    out["checks"].append({"key": "future", "title": "Future", "question": "Is the reason I bought still true?",
                          "status": st, "headline": head, "lines": lines, "news": news})

    # 4. team and governance
    g = blocks.get("governance") or {}
    gs, veto = g.get("score"), g.get("veto") or []
    neg = [e["text"] for e in g.get("evidence", []) if (e.get("points") or 0) < 0]
    if gs is None and not veto:
        st, head = "unknown", "No shareholding or audit data (/research)"
    else:
        st = "bad" if veto or (gs is not None and gs <= -0.5) else "watch" if neg or (gs is not None and gs < 0.5) else "good"
        head = ("Veto: " + "; ".join(veto)) if veto else f"Governance score {gs:+.1f}"
    out["checks"].append({"key": "team", "title": "Team and governance", "question": "Can I trust the people running it?",
                          "status": st, "headline": head, "lines": neg[:3] or [e["text"] for e in g.get("evidence", [])][:3]})

    # tax if sold now
    lots = [l for l in (lots if lots is not None else signal.get("tax_lots") or []) if l.get("symbol", sym) == sym]
    out["tax"] = {"lots": len(lots), "gain": round(sum(l.get("unrealised_gain") or 0 for l in lots), 0),
                  "tax_if_sold_now": round(sum(l.get("est_tax_if_sold") or 0 for l in lots), 0),
                  "next_long_term": min((l["long_term_from"] for l in lots
                                         if l.get("long_term_from") and (l.get("days_to_long_term") or 0) > 0), default=None)}
    bad = sum(c["status"] == "bad" for c in out["checks"])
    known = sum(c["status"] != "unknown" for c in out["checks"])
    broken = any(t_.startswith("thesis_broken") for t_ in out["triggers"])
    out["summary"] = {"bad": bad, "known": known,
                      "verdict": ("Review: several checks are concerns" if bad >= 2 or broken else
                                  "Watch: one check is a concern" if bad == 1 else
                                  "Holding case intact on the checks with data" if known else
                                  "Not enough data to judge")}
    return out


def sell_candidates(conn, cfg, run: dict, as_of: date) -> list[dict]:
    """Held stocks worth a sell review: label TRIM/SELL, a sell trigger, or 2+ concerns."""
    out = []
    for s in run["signals"]:
        if not s.get("held") or s.get("label") == "ETF":
            continue
        c = check(conn, cfg, s, as_of, run["tax"]["lots"])
        trig = [t for t in s.get("triggers", []) if t["type"] not in ("thesis_unchecked", "loss_watch")]
        if s.get("label") in ("TRIM", "SELL") or trig or c["summary"]["bad"] >= 2:
            out.append(c)
    order = {"SELL": 0, "TRIM": 1}
    return sorted(out, key=lambda c: (order.get(c["label"], 2), -c["summary"]["bad"]))
