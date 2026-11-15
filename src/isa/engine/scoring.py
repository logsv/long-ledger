"""Composite score, label, confidence, "why", and sell triggers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, timedelta

from .. import ENGINE_VERSION
from ..audit import append, now_utc
from ..config import Config
from . import fundamentals, governance, monitor, technicals, valuation
from .base import BlockResult, Data

LABELS = ("BUY", "ACCUMULATE", "HOLD", "TRIM", "SELL", "INSUFFICIENT_DATA", "ETF")
COMPANY_BLOCKS = ("fundamentals", "governance", "valuation")
_SEVERITY = {"BUY": 0, "ACCUMULATE": 1, "HOLD": 2, "TRIM": 3, "SELL": 4}
PHASE2_BLOCKS = ("macro", "sector", "events")


def label_for(composite: float, cuts: dict) -> str:
    if composite >= cuts["buy"]:
        return "BUY"
    if composite >= cuts["accumulate"]:
        return "ACCUMULATE"
    if composite > cuts["hold"]:
        return "HOLD"
    if composite > cuts["trim"]:
        return "TRIM"
    return "SELL"


def _at_least(label: str, floor: str) -> str:
    """Move label towards selling: never less severe than floor."""
    return label if _SEVERITY[label] >= _SEVERITY[floor] else floor


def _blocks(d: Data, symbol: str, cfg: Config) -> dict[str, BlockResult]:
    return {
        "fundamentals": fundamentals.evaluate(d, symbol),
        "governance": governance.evaluate(d, symbol, cfg.thresholds),
        "valuation": valuation.evaluate(d, symbol, cfg.valuation),
    }


def _metrics(blocks: dict[str, BlockResult], d: Data, symbol: str) -> dict[str, float]:
    """Every evidence value plus raw latest facts, for thesis conditions."""
    from ..importers.facts import METRICS
    out: dict[str, float] = {}
    for m in METRICS:
        latest = d.latest(symbol, m)
        if latest:
            out[m] = latest[1]
    for b in blocks.values():
        for e in b.evidence:
            if e.value is not None:
                out[e.key] = e.value
    return out


def _check_thesis(conn: sqlite3.Connection, symbol: str, metrics: dict) -> list[dict]:
    ops = {">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
           "<": lambda a, b: a < b, "<=": lambda a, b: a <= b}
    results = []
    for c in conn.execute("SELECT * FROM thesis_condition WHERE symbol = ? AND active = 1", (symbol,)):
        value = metrics.get(c["metric"])
        status = "unknown" if value is None else ("holds" if ops[c["op"]](value, c["threshold"]) else "broken")
        results.append({"id": c["id"], "metric": c["metric"], "op": c["op"], "threshold": c["threshold"],
                        "value": value, "status": status, "note": c["note"]})
    return results


def evaluate(conn: sqlite3.Connection, cfg: Config, symbol: str, as_of: date,
             position: dict | None = None, market_block: BlockResult | None = None) -> dict:
    """Score one stock as of a date. position = portfolio row if held.

    market_block (block a) is shared by all stocks in a run. It only counts
    when at least one company block has data: price and market data alone
    never produce a BUY/SELL label.
    """
    d = Data(conn, as_of)
    blocks = _blocks(d, symbol, cfg)
    w = cfg.weights["weights"]
    conf_cfg = cfg.weights["confidence"]
    min_c = conf_cfg["min_block_completeness"]
    used = {n: b for n, b in blocks.items() if b.score is not None and b.completeness >= min_c}
    if used and market_block is not None and market_block.score is not None \
            and market_block.completeness >= min_c:
        used["macro"] = market_block
    tech = technicals.evaluate(d, symbol, cfg.thresholds)
    sec = conn.execute("SELECT is_etf, asset_class, market_cap_bucket FROM security WHERE symbol = ?",
                       (symbol,)).fetchone()
    not_built = [b for b in PHASE2_BLOCKS if not (b == "macro" and market_block is not None)]

    result: dict = {
        "symbol": symbol, "as_of": as_of.isoformat(), "engine_version": ENGINE_VERSION,
        "blocks": {n: b.to_dict() for n, b in blocks.items()},
        "blocks_not_built": not_built, "technicals": tech, "held": bool(position),
        "asset_class": sec["asset_class"] if sec else None,
        "market_cap_bucket": sec["market_cap_bucket"] if sec else None,
        "flags": monitor.flags(d, symbol, tech, cfg.thresholds, position),
    }

    if sec and sec["is_etf"]:
        result.update(label="ETF", composite=None, confidence=0.0, triggers=[], veto=[],
                      why={"positive": [], "negative": [], "missing": []},
                      notes=["ETF: company analysis does not apply; see asset-class limits and timing"])
        result["inputs_hash"] = _hash(result, cfg)
        return result

    if not used:
        result.update(label="INSUFFICIENT_DATA", composite=None, confidence=0.0,
                      why={"positive": [], "negative": [],
                           "missing": [f"{n}: {b.completeness:.0%} of inputs" for n, b in blocks.items()]},
                      triggers=[], veto=[])
        result["inputs_hash"] = _hash(result, cfg)
        return result

    total_w = sum(w[n] for n in used)
    composite = sum(w[n] * used[n].score for n in used) / total_w
    label = label_for(composite, cfg.weights["labels"])
    notes: list[str] = []

    veto = blocks["governance"].veto
    if veto and label in ("BUY", "ACCUMULATE"):
        notes.append(f"{label} blocked by governance red flag: " + "; ".join(veto))
        label = "HOLD"

    # Confidence: coverage x completeness x agreement x freshness.
    all_w = sum(w.values())
    coverage = total_w / all_w
    completeness = sum(w[n] * used[n].completeness for n in used) / total_w
    agree = []
    for b in used.values():
        s = b.score
        if abs(composite) < 0.4:
            agree.append(1.0 if abs(s) <= 0.5 else 0.5)
        else:
            agree.append(1.0 if s * composite > 0 else 0.5 if s == 0 else 0.0)
    agreement = sum(agree) / len(agree)
    freshness = 1.0
    pub = d.latest_published(symbol)
    if not pub or (as_of - date.fromisoformat(pub)).days > conf_cfg["stale_fundamentals_days"]:
        freshness *= 0.7
        notes.append("fundamentals may be stale: no filing in the last ~15 months")
    lp = d.last_price(symbol)
    if not lp or (as_of - date.fromisoformat(lp[1])).days > conf_cfg["stale_price_days"]:
        freshness *= 0.8
        notes.append("price is not recent: run /sync")
    confidence = round(100 * coverage * completeness * agreement * freshness, 1)

    triggers: list[dict] = []
    if position:
        triggers = _sell_triggers(conn, cfg, symbol, as_of, blocks, d, position)
        for t in triggers:
            label = _at_least(label, t["min_label"])

    result.update(
        label=label, composite=round(composite, 3), confidence=confidence,
        confidence_parts={"coverage": round(coverage, 3), "completeness": round(completeness, 3),
                          "agreement": round(agreement, 3), "freshness": round(freshness, 3)},
        why=_why(used, w), triggers=triggers, veto=veto, notes=notes,
        timing=tech.get("advice") if label in ("BUY", "ACCUMULATE") else None,
    )
    result["inputs_hash"] = _hash(result, cfg)
    return result


def _sell_triggers(conn, cfg: Config, symbol: str, as_of: date, blocks, d: Data, position: dict) -> list[dict]:
    st = cfg.thresholds["sell_triggers"]
    out = []
    thesis = _check_thesis(conn, symbol, _metrics(blocks, d, symbol))
    broken = [t for t in thesis if t["status"] == "broken"]
    if broken:
        out.append({"type": "thesis_broken", "min_label": "SELL",
                    "detail": "; ".join(f"{t['metric']} {t['value']} is not {t['op']} {t['threshold']}"
                                        + (f" ({t['note']})" if t["note"] else "") for t in broken)})
    iv = blocks["valuation"].extra.get("intrinsic_value") or {}
    price = blocks["valuation"].extra.get("price")
    if price and iv.get("high") and price > iv["high"] * (1 + st["valuation_stretch"]):
        out.append({"type": "valuation_stretch", "min_label": "TRIM",
                    "detail": f"price {price:.1f} is {price / iv['high'] - 1:.0%} above the upper"
                              f" intrinsic value {iv['high']:.0f}"})
    loss = position.get("unrealised_pct")
    if loss is not None and loss <= -st["loss_threshold"]:
        past = Data(conn, as_of - timedelta(days=int(st["fundamentals_lookback_days"])))
        before = fundamentals.evaluate(past, symbol).score
        now = blocks["fundamentals"].score
        if before is not None and now is not None and before - now >= st["fundamentals_drop"]:
            out.append({"type": "loss_with_weakening_fundamentals", "min_label": "SELL",
                        "detail": f"down {loss:.0%} and fundamentals score fell from {before:.2f} to {now:.2f}"})
        else:
            out.append({"type": "loss_watch", "min_label": "BUY",  # informational only
                        "detail": f"down {loss:.0%}, but fundamentals have not weakened enough to sell"})
    if thesis and not broken:
        unknown = [t["metric"] for t in thesis if t["status"] == "unknown"]
        if unknown:
            out.append({"type": "thesis_unchecked", "min_label": "BUY",
                        "detail": "no data yet for: " + ", ".join(unknown)})
    return out


def _why(used: dict[str, BlockResult], w: dict) -> dict:
    lines = []
    for name, b in used.items():
        for e in b.scored:
            lines.append((e.points * w[name], e.points, f"{e.text} [{name}]"))
    pos = [t for s, _, t in sorted((x for x in lines if x[0] > 0), key=lambda x: -x[0])[:3]]
    neg = [t for s, _, t in sorted((x for x in lines if x[0] < 0), key=lambda x: x[0])[:3]]
    return {"positive": pos, "negative": neg}


def _hash(result: dict, cfg: Config) -> str:
    body = {k: v for k, v in result.items() if k != "inputs_hash"}
    raw = json.dumps({"r": body, "w": cfg.weights, "t": cfg.thresholds, "v": cfg.valuation},
                     sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def record(conn: sqlite3.Connection, result: dict) -> int:
    """Store a signal and audit it."""
    cur = conn.execute(
        "INSERT INTO signal(symbol, as_of, label, composite, confidence, engine_version, inputs_hash,"
        " payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (result["symbol"], result["as_of"], result["label"], result.get("composite"),
         result["confidence"], result["engine_version"], result["inputs_hash"],
         json.dumps(result, default=str), now_utc()),
    )
    append(conn, "signal", {"signal_id": cur.lastrowid, "label": result["label"],
                            "composite": result.get("composite"), "confidence": result["confidence"],
                            "inputs_hash": result["inputs_hash"],
                            "triggers": [t["type"] for t in result.get("triggers", [])]},
           symbol=result["symbol"])
    return cur.lastrowid
