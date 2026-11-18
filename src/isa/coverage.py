"""Company-data coverage per stock, and resolving research targets by symbol or company name."""

from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta
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
            "last_attempt": last_attempt(conn, symbol),
            "state": "full" if years >= 3 else "partial" if years or share else "none"}


def last_attempt(conn: sqlite3.Connection, symbol: str) -> dict | None:
    row = conn.execute("SELECT run_at, outcome, facts_stored, site, note FROM research_run WHERE symbol = ?"
                       " ORDER BY run_at DESC, id DESC LIMIT 1", (symbol,)).fetchone()
    return dict(row) if row else None


def expected_annual_period(as_of: date) -> str:
    """Latest financial year whose annual report should be out (AGMs finish by end-September)."""
    year = as_of.year if as_of.month >= 10 else as_of.year - 1
    return f"{year}-03-31"


def expected_shareholding_quarter(as_of: date) -> str:
    """Latest quarter end whose shareholding pattern is due (filed within 21 days)."""
    d = as_of - timedelta(days=21)
    for y in (d.year, d.year - 1):
        for m, dd in ((12, 31), (9, 30), (6, 30), (3, 31)):
            q = date(y, m, dd)
            if q <= d:
                return q.isoformat()
    return d.isoformat()


def buckets(st: dict, as_of: date, older_than_days: int | None = None) -> tuple[list[str], list[str]]:
    """Research buckets for one stock: new, incomplete, stale or current, with reasons."""
    attempt = st.get("last_attempt")
    out, why = [], []
    if st["state"] == "none" and not attempt:
        return ["new"], ["never researched"]
    if attempt and attempt["outcome"] in ("failed", "partial"):
        out.append("incomplete")
        why.append(f"last run {attempt['outcome']} on {attempt['run_at'][:10]}"
                   + (f": {attempt['note']}" if attempt.get("note") else ""))
    elif st["state"] == "none":
        out.append("incomplete")
        why.append("researched but no confirmed data")
    if st["state"] == "partial":
        out.append("incomplete") if "incomplete" not in out else None
        why.append(f"only {st['annual_years']} annual year(s)")
    if st["pending_facts"]:
        out.append("incomplete") if "incomplete" not in out else None
        why.append(f"{st['pending_facts']} pending fact(s)")
    if st["state"] != "none":
        exp_a, exp_q = expected_annual_period(as_of), expected_shareholding_quarter(as_of)
        stale = []
        if (st["latest_annual_period"] or "") < exp_a:
            stale.append(f"annual data to {st['latest_annual_period'] or 'none'}, FY ending {exp_a} is out")
        if (st["latest_shareholding_quarter"] or "") < exp_q:
            stale.append(f"shareholding to {st['latest_shareholding_quarter'] or 'none'}, quarter {exp_q} is due")
        if older_than_days is not None and st.get("last_imported"):
            if st["last_imported"][:10] < (as_of - timedelta(days=older_than_days)).isoformat():
                stale.append(f"last imported {st['last_imported'][:10]}, over {older_than_days} days ago")
        if stale:
            out.append("stale")
            why += stale
    return (out or ["current"]), why


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
