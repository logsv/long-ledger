"""Company-data coverage per stock, and resolving research targets by symbol or company name."""

from __future__ import annotations

import re
import sqlite3
from urllib.parse import urlparse

_SUFFIX = re.compile(r"\b(limited|ltd|the|india|inc|co|company|corporation|corp)\b\.?", re.IGNORECASE)


def norm_name(name: str | None) -> str:
    s = _SUFFIX.sub(" ", (name or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def status(conn: sqlite3.Connection, symbol: str) -> dict:
    """What confirmed company data exists for one stock, and where it came from."""
    ok = "(extracted_by != 'llm' OR confirmed = 1)"
    annual = conn.execute(
        f"SELECT COUNT(DISTINCT period_end), MAX(period_end) FROM fundamental_fact"
        f" WHERE symbol = ? AND metric = 'revenue' AND {ok}", (symbol,)).fetchone()
    share = conn.execute(
        f"SELECT MAX(period_end) FROM fundamental_fact WHERE symbol = ? AND metric = 'promoter_pct' AND {ok}",
        (symbol,)).fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM fundamental_fact WHERE symbol = ? AND confirmed = 0",
                           (symbol,)).fetchone()[0]
    refs = [r[0] for r in conn.execute(
        f"SELECT DISTINCT source_ref FROM fundamental_fact WHERE symbol = ? AND {ok} AND source_ref LIKE 'http%'",
        (symbol,))]
    sites = sorted({urlparse(r.split()[0]).netloc.removeprefix("www.") for r in refs if r})
    last = conn.execute(
        "SELECT MAX(l.imported_at) FROM import_log l JOIN fundamental_fact f ON f.import_id = l.id"
        " WHERE f.symbol = ?", (symbol,)).fetchone()[0]
    years = annual[0] or 0
    return {"annual_years": years, "latest_annual_period": annual[1], "latest_shareholding_quarter": share,
            "pending_facts": pending, "sites": sites, "last_imported": last,
            "state": "full" if years >= 3 else "partial" if years or share else "none"}


def resolve(conn: sqlite3.Connection, query: str) -> dict:
    """A symbol if it exists; else match by company name. Never guesses between candidates."""
    q = query.strip()
    row = conn.execute("SELECT symbol, name, isin FROM security WHERE symbol = ? AND is_index = 0",
                       (q.upper(),)).fetchone()
    if row:
        return {"query": q, "symbol": row["symbol"], "name": row["name"], "isin": row["isin"], "match": "symbol"}
    nq = norm_name(q)
    if not nq:
        return {"query": q, "symbol": None, "match": "none"}
    rows = conn.execute("SELECT symbol, name, isin FROM security WHERE is_index = 0 AND name IS NOT NULL").fetchall()
    exact = [r for r in rows if norm_name(r["name"]) == nq]
    partial = exact or [r for r in rows if nq in norm_name(r["name"])]
    if len(partial) == 1:
        r = partial[0]
        return {"query": q, "symbol": r["symbol"], "name": r["name"], "isin": r["isin"], "match": "name"}
    if partial:
        return {"query": q, "symbol": None, "match": "ambiguous",
                "candidates": [{"symbol": r["symbol"], "name": r["name"]} for r in partial[:10]]}
    return {"query": q, "symbol": None, "name": q, "match": "new",
            "note": "not in the database: the researcher identifies the NSE symbol and ISIN from the company's site"}
