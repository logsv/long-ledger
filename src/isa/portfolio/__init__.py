"""Positions, weights, concentration caps and broker reconciliation."""

from __future__ import annotations

import sqlite3
from collections import defaultdict

from ..tax import LotBook


def latest_prices(conn: sqlite3.Connection) -> dict[str, tuple[float, str]]:
    """symbol -> (close, date) from daily prices; snapshot price as fallback."""
    out: dict[str, tuple[float, str]] = {}
    for r in conn.execute(
        "SELECT p.symbol, p.close, p.date FROM price_daily p JOIN"
        " (SELECT symbol, MAX(date) d FROM price_daily GROUP BY symbol) m"
        " ON p.symbol = m.symbol AND p.date = m.d"
    ):
        out[r["symbol"]] = (r["close"], r["date"])
    for r in conn.execute(
        "SELECT h.symbol, h.last_price, h.as_of FROM holding_snapshot h JOIN"
        " (SELECT source, MAX(as_of) a FROM holding_snapshot GROUP BY source) m"
        " ON h.source = m.source AND h.as_of = m.a WHERE h.last_price IS NOT NULL"
    ):
        if r["symbol"] not in out or out[r["symbol"]][1] < r["as_of"]:
            out[r["symbol"]] = (r["last_price"], r["as_of"])
    return out


def latest_snapshots(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Rows of each source's most recent holdings snapshot."""
    return conn.execute(
        "SELECT h.* FROM holding_snapshot h JOIN"
        " (SELECT source, MAX(as_of) a FROM holding_snapshot GROUP BY source) m"
        " ON h.source = m.source AND h.as_of = m.a ORDER BY h.symbol"
    ).fetchall()


def positions(conn: sqlite3.Connection, book: LotBook) -> dict[str, dict]:
    """Combined position per symbol across brokers.

    Quantities come from the latest broker snapshots. A symbol with lots but no
    snapshot (e.g. a broker that was never synced) is taken from the lots.
    """
    pos: dict[str, dict] = {}
    snap_sources: set[str] = set()
    for r in latest_snapshots(conn):
        snap_sources.add(r["source"])
        p = pos.setdefault(r["symbol"], {"symbol": r["symbol"], "quantity": 0.0, "cost": 0.0,
                                         "cost_known": True, "accounts": []})
        p["quantity"] += r["quantity"]
        if r["avg_price"] is None:
            p["cost_known"] = False
        else:
            p["cost"] += r["quantity"] * r["avg_price"]
        p["accounts"].append(r["source"])
    for lot in book.open_lots:
        if lot.account in snap_sources:
            continue
        p = pos.setdefault(lot.symbol, {"symbol": lot.symbol, "quantity": 0.0, "cost": 0.0,
                                        "cost_known": True, "accounts": []})
        p["quantity"] += lot.quantity
        p["cost"] += lot.quantity * lot.cost
        if lot.account not in p["accounts"]:
            p["accounts"].append(lot.account)
    return pos


def portfolio_view(conn: sqlite3.Connection, book: LotBook, thresholds: dict) -> dict:
    caps = thresholds["portfolio"]
    prices = latest_prices(conn)
    pos = positions(conn, book)
    sec = {r["symbol"]: r for r in conn.execute(
        "SELECT symbol, sector, asset_class, market_cap_bucket, is_etf FROM security")}
    sectors = {s: r["sector"] for s, r in sec.items()}
    rows, total = [], 0.0
    for sym, p in sorted(pos.items()):
        price = prices.get(sym, (None, None))
        value = p["quantity"] * price[0] if price[0] else None
        if value:
            total += value
        r = sec.get(sym)
        rows.append({**p, "price": price[0], "price_date": price[1], "value": value,
                     "sector": sectors.get(sym) or "Unclassified",
                     "asset_class": (r["asset_class"] if r and r["asset_class"] else "unknown"),
                     "market_cap_bucket": (r["market_cap_bucket"] if r else None),
                     "is_etf": bool(r and r["is_etf"])})
    by_sector: dict[str, float] = defaultdict(float)
    breaches = []
    for r in rows:
        r["weight"] = (r["value"] / total) if (r["value"] and total) else None
        if r["cost_known"] and r["cost"] and r["value"] is not None:
            r["unrealised_pct"] = r["value"] / r["cost"] - 1
        else:
            r["unrealised_pct"] = None
        r["avg_cost"] = (r["cost"] / r["quantity"]) if (r["cost_known"] and r["quantity"]) else None
        if r["value"]:
            by_sector[r["sector"]] += r["value"]
        if r["weight"] is not None and r["weight"] > caps["max_stock_weight"]:
            breaches.append({"type": "stock", "name": r["symbol"], "weight": r["weight"],
                             "cap": caps["max_stock_weight"]})
    sector_rows = []
    for name, v in sorted(by_sector.items(), key=lambda kv: -kv[1]):
        w = v / total if total else 0.0
        sector_rows.append({"sector": name, "value": v, "weight": w})
        if name != "Unclassified" and w > caps["max_sector_weight"]:
            breaches.append({"type": "sector", "name": name, "weight": w,
                             "cap": caps["max_sector_weight"]})
    by_asset: dict[str, float] = defaultdict(float)
    by_cap: dict[str, float] = defaultdict(float)
    for r in rows:
        if r["value"]:
            by_asset[r["asset_class"]] += r["value"]
            if not r["is_etf"]:
                by_cap[r["market_cap_bucket"] or "unknown"] += r["value"]
    asset_rows = [{"asset_class": k, "value": v, "weight": v / total if total else 0.0}
                  for k, v in sorted(by_asset.items(), key=lambda kv: -kv[1])]
    cap_rows = [{"bucket": k, "value": v, "weight": v / total if total else 0.0}
                for k, v in sorted(by_cap.items(), key=lambda kv: -kv[1])]
    precious = sum(v for k, v in by_asset.items() if k in ("gold", "silver"))
    if total and precious / total > caps["max_precious_metals_weight"]:
        breaches.append({"type": "asset_class", "name": "gold + silver", "weight": precious / total,
                         "cap": caps["max_precious_metals_weight"]})
    if total and by_cap.get("small", 0) / total > caps["max_small_cap_weight"]:
        breaches.append({"type": "market_cap", "name": "small caps", "weight": by_cap["small"] / total,
                         "cap": caps["max_small_cap_weight"]})
    weights = sorted((r["weight"] for r in rows if r["weight"]), reverse=True)
    return {
        "total_value": total,
        "holdings": rows,
        "sectors": sector_rows,
        "asset_classes": asset_rows,
        "market_caps": cap_rows,
        "unclassified_assets": [r["symbol"] for r in rows if r["asset_class"] == "unknown"],
        "top5_weight": sum(weights[:5]),
        "breaches": breaches,
        "missing_price": [r["symbol"] for r in rows if r["price"] is None],
        "unclassified": [r["symbol"] for r in rows if r["sector"] == "Unclassified"],
        "reconciliation": reconcile(conn, book),
    }


def reconcile(conn: sqlite3.Connection, book: LotBook) -> list[dict]:
    """Snapshot quantity vs open-lot quantity, per broker account."""
    lot_qty: dict[tuple[str, str], float] = defaultdict(float)
    for lot in book.open_lots:
        lot_qty[(lot.account, lot.symbol)] += lot.quantity
    snap_qty = {(r["source"], r["symbol"]): r["quantity"] for r in latest_snapshots(conn)}
    synced_sources = {k[0] for k in snap_qty}
    traded_accounts = {k[0] for k in lot_qty}
    issues = []
    for key in sorted(set(snap_qty) | set(lot_qty)):
        account, sym = key
        if account not in synced_sources or account not in traded_accounts:
            continue  # nothing to compare against for this broker yet
        s, l_ = snap_qty.get(key, 0.0), lot_qty.get(key, 0.0)
        if abs(s - l_) > 1e-6:
            issues.append({"account": account, "symbol": sym, "broker_quantity": s,
                           "lot_quantity": l_,
                           "hint": "import missing trades (older tradebook) or a corporate action"})
    lots_missing = sorted({k[0] for k in snap_qty} - traded_accounts)
    for account in lots_missing:
        issues.append({"account": account, "symbol": None, "broker_quantity": None,
                       "lot_quantity": None,
                       "hint": "no trades imported for this broker: tax view needs its tradebook"})
    return issues
