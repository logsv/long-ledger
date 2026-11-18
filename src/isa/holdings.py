"""Latest holdings per broker, with INDmoney's consolidated view de-duplicated.

INDmoney links your other demat accounts (Kite, 5paisa) and reports one total per
stock across all of them, labelled as a single broker. Adding that total to the
Kite and 5paisa quantities we fetch directly counts the same shares twice.

So for a stock that Kite or 5paisa also hold, only the part of INDmoney's total
that is beyond them counts as INDmoney's own (floor 0). Each such stock carries
an `overlap` note so the difference can be checked in the INDmoney app: its copy
of the other brokers can be a day or two old.
"""

from __future__ import annotations

import sqlite3

AGGREGATORS = ("indmoney",)


def effective_snapshots(conn: sqlite3.Connection) -> list[dict]:
    """Latest snapshot rows; INDmoney rows reduced to the part beyond Kite/5paisa, dropped if nothing is left."""
    return [r for r in effective_snapshots_all(conn) if not r.get("overlap") or r["quantity"] > 1e-9]


def overlaps(conn: sqlite3.Connection) -> list[dict]:
    """Stocks where INDmoney's total includes shares held at Kite or 5paisa."""
    return [{"source": r["source"], "symbol": r["symbol"], **r["overlap"]}
            for r in effective_snapshots_all(conn) if r.get("overlap")]


def effective_snapshots_all(conn: sqlite3.Connection) -> list[dict]:
    """Like effective_snapshots, but keeps rows whose own quantity is zero (for reporting)."""
    rows = [dict(r) for r in conn.execute(
        "SELECT h.* FROM holding_snapshot h JOIN"
        " (SELECT source, MAX(as_of) a FROM holding_snapshot GROUP BY source) m"
        " ON h.source = m.source AND h.as_of = m.a ORDER BY h.symbol")]
    direct: dict[str, float] = {}
    for r in rows:
        if r["source"] not in AGGREGATORS:
            direct[r["symbol"]] = direct.get(r["symbol"], 0.0) + r["quantity"]
    for r in rows:
        if r["source"] in AGGREGATORS and r["symbol"] in direct:
            own = max(0.0, r["quantity"] - direct[r["symbol"]])
            r["overlap"] = {"aggregator_total": r["quantity"], "other_brokers": direct[r["symbol"]], "counted": own}
            r["quantity"] = own
    return rows
