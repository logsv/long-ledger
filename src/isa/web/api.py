"""JSON views for the local dashboard. Read-only: every function only reads.

Rows are shaped for Tabulator tables (flat dicts, plain values).
"""

from __future__ import annotations

import sqlite3

BROKERS = {"kite": "Zerodha", "fivepaisa": "5paisa", "indmoney": "INDmoney", "manual": "Manual"}
FLAG_NAMES = {"weak_trend": "Weak trend", "deep_drawdown": "Deep drawdown",
              "volume_spike": "Volume spike", "loss_from_cost": "Loss from cost"}
ORIGINS = (("indtax|", "INDmoney tax report"), ("xfer|", "Transfer in"), ("demerger|", "Demerger"),
           ("5ptx|", "5paisa statement"))


def broker(name: str | None) -> str:
    return BROKERS.get(name or "", name or "")


def _r(x, n=2):
    return None if x is None else round(x, n)


def overview(run: dict, conn: sqlite3.Connection) -> dict:
    pv, sigs, tax, mk = run["portfolio"], run["signals"], run["tax"], run.get("market") or {}
    cov = run.get("coverage") or {}
    weights = {h["symbol"]: h.get("weight") or 0 for h in pv["holdings"]}
    full = [s for s, c in cov.items() if c["state"] == "full"]
    labels: dict[str, int] = {}
    for s in sigs:
        labels[s["label"]] = labels.get(s["label"], 0) + 1
    synced = [{"broker": broker(r[0]), "holdings_as_of": r[1]} for r in conn.execute(
        "SELECT source, MAX(as_of) FROM holding_snapshot GROUP BY source ORDER BY source")]
    last_trade = {broker(r[0]): r[1] for r in conn.execute(
        "SELECT account, MAX(trade_date) FROM trade GROUP BY account")}
    for s in synced:
        s["last_trade"] = last_trade.get(s["broker"])
    return {
        "as_of": run["as_of"],
        "total_value": _r(pv["total_value"], 0),
        "holdings": len(pv["holdings"]),
        "top5_weight": pv["top5_weight"],
        "labels": labels,
        "flagged": sum(1 for s in sigs if s["held"] and s.get("flags")),
        "company_data": {"full": len(full), "of": len(cov),
                         "value_share": round(sum(weights.get(s, 0) for s in full), 4)},
        "regime": mk.get("regime"),
        "market_lines": [e["text"] for e in (mk.get("block") or {}).get("evidence", [])],
        "market_missing": mk.get("missing", []),
        "sectors": [{"index": s["index"], "ret_3m": _r(s["ret_3m"], 4), "ret_6m": _r(s.get("ret_6m"), 4)}
                    for s in mk.get("sectors", [])],
        "asset_classes": [{"name": r["asset_class"], "weight": round(r["weight"], 4)} for r in pv.get("asset_classes", [])],
        "market_caps": [{"name": r["bucket"], "weight": round(r["weight"], 4)} for r in pv.get("market_caps", [])],
        "breaches": [{"what": b["name"] if b["type"] not in ("stock", "sector") else f"{b['type'].title()} {b['name']}",
                      "weight": round(b["weight"], 4), "limit": b["cap"]} for b in pv["breaches"]],
        "reconciliation": [{"broker": broker(r["account"]), "symbol": r["symbol"], "note": r["hint"]}
                           for r in pv["reconciliation"]],
        "tax": {"ltcg_exemption_remaining": tax["ltcg_exemption_remaining"],
                "ltcg_realised_this_fy": tax["ltcg_realised_this_fy"],
                "wait_lots": sum(1 for l in tax["lots"] if l.get("wait_until")),
                "estimated_lots": tax.get("estimated_lots", 0),
                "unmatched_sells": len(tax.get("unmatched_sells", []))},
        "pending_facts": run["pending_facts"],
        "synced": synced,
    }


def holdings(run: dict) -> list[dict]:
    sigs = {s["symbol"]: s for s in run["signals"]}
    cov = run.get("coverage") or {}
    names = run.get("names") or {}
    rows = []
    for h in run["portfolio"]["holdings"]:
        s = sigs.get(h["symbol"], {})
        by = sorted((h.get("by_account") or {}).items(), key=lambda kv: -kv[1])
        c = cov.get(h["symbol"]) or {}
        flags = s.get("flags", [])
        rows.append({
            "symbol": h["symbol"], "name": names.get(h["symbol"]) or "",
            "brokers": ", ".join(f"{broker(a)} {q:g}" for a, q in by),
            "broker_list": [broker(a) for a, _ in by],
            "quantity": h["quantity"], "avg_cost": _r(h.get("avg_cost")), "price": _r(h.get("price")),
            "value": _r(h.get("value"), 0), "weight": _r(h.get("weight"), 5),
            "pnl_pct": _r(h.get("unrealised_pct"), 5),
            "asset_class": h.get("asset_class"), "market_cap": h.get("market_cap_bucket") or "",
            "sector": h.get("sector"), "is_etf": h.get("is_etf", False),
            "label": s.get("label", ""), "confidence": s.get("confidence"),
            "why": "; ".join((s.get("why") or {}).get("positive", []) + (s.get("why") or {}).get("negative", [])),
            "triggers": "; ".join(f"{t['type']}: {t['detail']}" for t in s.get("triggers", [])),
            "flags": [FLAG_NAMES.get(f["type"], f["type"]) for f in flags],
            "flag_detail": "; ".join(f"{FLAG_NAMES.get(f['type'], f['type'])}: {f['detail']}" for f in flags),
            "flag_count": len(flags),
            "trend": ((s.get("technicals") or {}).get("stance") or "").capitalize(),
            "data_state": "ETF" if h.get("is_etf") else (c.get("state") or "none"),
            "data_years": c.get("annual_years"), "pending_facts": c.get("pending_facts", 0),
        })
    return rows


def trades(conn: sqlite3.Connection) -> list[dict]:
    names = {r[0]: r[1] for r in conn.execute("SELECT symbol, name FROM security")}
    out = []
    for r in conn.execute("SELECT trade_date, account, symbol, side, quantity, price, trade_id FROM trade"
                          " ORDER BY trade_date DESC, id DESC"):
        tid = r[6] or ""
        origin = next((label for prefix, label in ORIGINS if tid.startswith(prefix)), "Tradebook / API")
        out.append({"date": r[0], "broker": broker(r[1]), "symbol": r[2], "name": names.get(r[2]) or "",
                    "side": r[3], "quantity": r[4], "price": r[5], "value": round(r[4] * r[5], 2),
                    "origin": origin})
    return out


def lots(run: dict) -> list[dict]:
    names = run.get("names") or {}
    out = []
    for l in run["tax"]["lots"]:
        out.append({
            "symbol": l["symbol"], "name": names.get(l["symbol"]) or "", "broker": broker(l["account"]),
            "bought": f"before {l['acquired_before']}" if l.get("estimated") else l["buy_date"],
            "origin": {"trade": "Trade", "opening": "Estimated (pre-history)", "transfer_in": "Transfer in",
                       "demerger": "Demerger"}.get(l.get("origin", "trade"), l.get("origin")),
            "quantity": round(l["quantity"], 4), "cost": _r(l["cost"]), "price": _r(l.get("price")),
            "gain": l.get("unrealised_gain"), "term": l["term_if_sold_today"],
            "long_term_from": l.get("long_term_from"), "days_to_long_term": l.get("days_to_long_term"),
            "wait_until": l.get("wait_until"), "est_tax": l.get("est_tax_if_sold"), "note": l.get("note") or "",
        })
    return out


def quality(run: dict, conn: sqlite3.Connection) -> dict:
    tax = run["tax"]
    names = run.get("names") or {}
    pending = [dict(r) for r in conn.execute(
        "SELECT id, symbol, metric, period_end, value, source, source_ref FROM fundamental_fact"
        " WHERE confirmed = 0 ORDER BY symbol, metric")]
    return {
        "unmatched_sells": [{"broker": broker(u["account"]), "symbol": u["symbol"],
                             "name": names.get(u["symbol"]) or "", "sell_date": u["sell_date"],
                             "quantity": u["unmatched_quantity"]} for u in tax.get("unmatched_sells", [])],
        "pending_facts": pending,
        "unclassified": run["portfolio"].get("unclassified_assets", []),
        "missing_price": run["portfolio"].get("missing_price", []),
        "reconciliation": [{"broker": broker(r["account"]), "symbol": r["symbol"], "note": r["hint"]}
                           for r in run["portfolio"]["reconciliation"]],
    }
