"""Fundamental and shareholding facts.

Long format, one number per row:
    symbol, metric, period_end, published_at, value, source, source_ref

Amounts are in INR crore unless the metric says otherwise; percentages are
plain numbers (12.5 means 12.5%). Facts extracted by Claude from documents
arrive with extracted_by='llm' and are ignored by the engine until confirmed.
"""

from __future__ import annotations

import sqlite3

from ..audit import append
from ..storage.db import ensure_security, normalize_symbol
from .broker import _finish_import, _start_import
from .common import ImportError_, parse_date, parse_number, pick

# metric -> (unit, description). Unknown metrics are rejected to catch typos.
METRICS: dict[str, tuple[str, str]] = {
    # Annual financials (period_end = fiscal year end)
    "revenue": ("INR cr", "Revenue from operations"),
    "ebitda": ("INR cr", "Operating profit before depreciation"),
    "ebit": ("INR cr", "Profit before interest and tax"),
    "pat": ("INR cr", "Net profit attributable to shareholders"),
    "eps": ("INR", "Diluted EPS"),
    "total_equity": ("INR cr", "Shareholders' funds"),
    "total_debt": ("INR cr", "Borrowings, long + short term"),
    "cash": ("INR cr", "Cash and equivalents + liquid investments"),
    "interest_expense": ("INR cr", "Finance costs"),
    "cfo": ("INR cr", "Cash flow from operations"),
    "capex": ("INR cr", "Purchase of fixed assets (positive number)"),
    "dividend_per_share": ("INR", "Dividend per share for the year"),
    "shares_outstanding": ("crore shares", "Shares outstanding at year end"),
    "receivable_days": ("days", "Debtor days"),
    "inventory_days": ("days", "Inventory days"),
    "payable_days": ("days", "Creditor days"),
    "rpt_pct_revenue": ("%", "Related-party transactions as % of revenue"),
    "auditor_qualified": ("0/1", "1 if the audit opinion is qualified/adverse"),
    "auditor_resigned": ("0/1", "1 if the statutory auditor resigned mid-term"),
    # Shareholding pattern (period_end = quarter end)
    "promoter_pct": ("%", "Promoter and promoter group holding"),
    "promoter_pledge_pct": ("%", "Promoter shares pledged, % of promoter holding"),
    "fii_pct": ("%", "FII/FPI holding"),
    "dii_pct": ("%", "DII holding (incl. MF)"),
    "mf_pct": ("%", "Mutual fund holding"),
}

EXTRACTED_BY = ("user", "import", "llm")


ORIGINS = ("official", "third_party", "model")


def import_facts(conn: sqlite3.Connection, records: list[dict], source: str,
                 extracted_by: str = "import", file_name: str | None = None) -> dict:
    if extracted_by not in EXTRACTED_BY:
        raise ImportError_(f"extracted_by must be one of {EXTRACTED_BY}")
    import_id = _start_import(conn, "facts", source, file_name)
    confirmed = 0 if extracted_by == "llm" else 1
    stored, skipped = 0, []
    for i, row in enumerate(records):
        try:
            metric = str(pick(row, ("metric",)) or "").strip().lower()
            if metric not in METRICS:
                raise ImportError_(f"unknown metric {metric!r}")
            sym = pick(row, ("symbol",))
            if not sym:
                raise ImportError_("no symbol")
            sym = normalize_symbol(sym)
            value = parse_number(pick(row, ("value",)))
            if value is None:
                raise ImportError_("no value")
            period_end = parse_date(pick(row, ("period_end",)))
            published_at = parse_date(pick(row, ("published_at",)))
            if published_at < period_end:
                raise ImportError_("published_at is before period_end")
            if extracted_by == "llm" and not pick(row, ("source_ref",)):
                raise ImportError_("LLM-extracted facts need source_ref (document + page)")
            row_source = pick(row, ("source",)) or source
            origin = str(pick(row, ("origin",)) or "official").strip().lower()
            if origin not in ORIGINS:
                raise ImportError_(f"origin must be one of {ORIGINS}")
            if origin != "official" and extracted_by != "llm":
                raise ImportError_("third-party and model facts must be imported with --extracted-by llm")
            ensure_security(conn, sym)
            conn.execute(
                "INSERT INTO fundamental_fact(symbol, metric, period_end, published_at, value,"
                " source, source_ref, extracted_by, confirmed, import_id, origin)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(symbol, metric, period_end, source) DO UPDATE SET"
                " value = excluded.value, published_at = excluded.published_at,"
                " source_ref = excluded.source_ref, extracted_by = excluded.extracted_by,"
                " confirmed = excluded.confirmed, import_id = excluded.import_id, origin = excluded.origin",
                (sym, metric, period_end, published_at, value, row_source,
                 pick(row, ("source_ref",)), extracted_by, confirmed, import_id, origin),
            )
            stored += 1
        except ImportError_ as exc:
            skipped.append({"row": i, "reason": str(exc)})
    _finish_import(conn, import_id, stored)
    return {"import_id": import_id, "stored": stored, "skipped": skipped,
            "pending_confirmation": stored if extracted_by == "llm" else 0}


def pending_facts(conn: sqlite3.Connection, symbol: str | None = None) -> list[dict]:
    q = ("SELECT id, symbol, metric, period_end, published_at, value, source, source_ref, origin"
         " FROM fundamental_fact WHERE confirmed = 0")
    args: tuple = ()
    if symbol:
        q += " AND symbol = ?"
        args = (normalize_symbol(symbol),)
    return [dict(r) for r in conn.execute(q + " ORDER BY symbol, metric, period_end", args)]


def confirm_facts(conn: sqlite3.Connection, ids: list[int]) -> int:
    n = 0
    for fid in ids:
        row = conn.execute("SELECT symbol, metric, period_end, value FROM fundamental_fact"
                           " WHERE id = ? AND confirmed = 0", (fid,)).fetchone()
        if not row:
            continue
        conn.execute("UPDATE fundamental_fact SET confirmed = 1 WHERE id = ?", (fid,))
        append(conn, "fact_confirmed", {"fact_id": fid, "metric": row["metric"],
                                        "period_end": row["period_end"], "value": row["value"]},
               symbol=row["symbol"])
        n += 1
    return n


PCT_METRICS = {"promoter_pct", "promoter_pledge_pct", "fii_pct", "dii_pct", "mf_pct", "rpt_pct_revenue"}
FLAG_METRICS = {"auditor_qualified", "auditor_resigned"}


def check_facts(conn: sqlite3.Connection, symbol: str | None = None, source: str | None = None,
                today: str | None = None) -> list[dict]:
    """Consistency checks on facts (pending or confirmed). Returns issues; empty = passed.

    Catches typical extraction mistakes: lakh vs crore, swapped columns,
    standalone vs consolidated mix-ups, impossible percentages.
    """
    from datetime import date as _date
    today = today or _date.today().isoformat()
    q = "SELECT * FROM fundamental_fact WHERE 1=1"
    args: list = []
    if symbol:
        q += " AND symbol = ?"
        args.append(normalize_symbol(symbol))
    if source:
        q += " AND source = ?"
        args.append(source)
    rows = [dict(r) for r in conn.execute(q, args)]
    issues: list[dict] = []

    def issue(r, msg):
        issues.append({"id": r["id"], "symbol": r["symbol"], "metric": r["metric"],
                       "period_end": r["period_end"], "value": r["value"], "issue": msg})

    by: dict[tuple, dict[str, dict]] = {}
    for r in rows:
        by.setdefault((r["symbol"], r["period_end"]), {})[r["metric"]] = r
        if r["published_at"] > today:
            issue(r, "published_at is in the future")
        if r["metric"] in PCT_METRICS and not 0 <= r["value"] <= 100:
            issue(r, "percentage outside 0-100")
        if r["metric"] in FLAG_METRICS and r["value"] not in (0, 1):
            issue(r, "flag must be 0 or 1")
        if r["metric"] in ("capex", "shares_outstanding", "revenue") and r["value"] < 0:
            issue(r, "must not be negative")
    for (sym, period), m in by.items():
        v = {k: x["value"] for k, x in m.items()}
        if {"eps", "pat", "shares_outstanding"} <= v.keys() and v["shares_outstanding"] > 0 and v["eps"]:
            implied = v["pat"] / v["shares_outstanding"]
            if abs(implied - v["eps"]) > 0.15 * abs(v["eps"]) + 0.5:
                issue(m["eps"], f"EPS {v['eps']} vs PAT/shares {implied:.2f}: check units (crore) or consolidated vs standalone")
        for small, big in (("ebit", "ebitda"), ("ebitda", "revenue"), ("pat", "revenue")):
            if small in v and big in v and v[big] > 0 and v[small] > v[big] * 1.05:
                issue(m[small], f"{small} {v[small]} exceeds {big} {v[big]}")
    series: dict[tuple, list] = {}
    for r in rows:
        if r["metric"] == "revenue":
            series.setdefault((r["symbol"], r["source"]), []).append(r)
    for lst in series.values():
        lst.sort(key=lambda r: r["period_end"])
        for a, b in zip(lst, lst[1:]):
            if a["value"] > 0 and not 0.2 <= b["value"] / a["value"] <= 4:
                issue(b, f"revenue jumps from {a['value']} to {b['value']}: possible unit error")
    return issues


def confirm_source(conn: sqlite3.Connection, source: str, require_checks: bool = True) -> dict:
    """Confirm all pending facts from one document, optionally only if its checks pass."""
    pending = [r["id"] for r in conn.execute(
        "SELECT id FROM fundamental_fact WHERE source = ? AND confirmed = 0", (source,))]
    if require_checks:
        unofficial = conn.execute(
            "SELECT DISTINCT origin FROM fundamental_fact WHERE source = ? AND confirmed = 0 AND origin != 'official'",
            (source,)).fetchall()
        if unofficial:  # third-party and model facts need a blind second reading (importers/verify.py)
            kinds = ", ".join(sorted(r[0] for r in unofficial))
            return {"confirmed": 0, "pending": len(pending), "issues": [
                {"source": source, "issue": f"{kinds} facts are confirmed only by a matching independent reading (verify-facts)"}]}
        issues = check_facts(conn, source=source)
        if issues:
            return {"confirmed": 0, "pending": len(pending), "issues": issues}
    return {"confirmed": confirm_facts(conn, pending), "pending": 0, "issues": []}
