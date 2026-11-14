"""Synthetic test data. Nothing here is real company data."""

from __future__ import annotations

import atexit
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from isa.config import Config  # noqa: E402
from isa.importers.facts import import_facts  # noqa: E402
from isa.importers.market import import_prices, import_securities  # noqa: E402
from isa.storage.db import connect  # noqa: E402

AS_OF = date(2026, 11, 14)


def cfg() -> Config:
    return Config.load()


def db():
    conn = connect(":memory:")
    _OPEN.append(conn)  # closed at exit instead of warning at garbage collection
    return conn


_OPEN: list = []
atexit.register(lambda: [c.close() for c in _OPEN])


def annual_facts(symbol: str, revenue0: float, growth: float, margin: float, margin_step: float,
                 debt: float = 50.0, pledge: float = 0.0, pledge_prev: float | None = None,
                 qualified: int = 0, rpt: float = 1.0, shares0: float = 10.0, share_growth: float = 0.0,
                 years=range(2021, 2027)) -> list[dict]:
    rows = []
    equity = 500.0
    for i, y in enumerate(years):
        pe, pub = f"{y}-03-31", f"{y}-05-20"
        rev = revenue0 * (1 + growth) ** i
        ebitda = rev * (margin + margin_step * i)
        ebit = ebitda * 0.85
        pat = ebit * 0.7
        shares = shares0 * (1 + share_growth) ** i
        equity += pat * 0.7
        vals = {
            "revenue": rev, "ebitda": ebitda, "ebit": ebit, "pat": pat, "eps": pat / shares,
            "total_equity": equity, "total_debt": debt, "cash": 40.0, "interest_expense": 5.0,
            "cfo": pat * 1.1, "capex": pat * 0.3, "dividend_per_share": pat / shares * 0.3,
            "shares_outstanding": shares, "receivable_days": 40.0, "inventory_days": 30.0,
            "payable_days": 35.0 + i, "rpt_pct_revenue": rpt, "auditor_qualified": qualified,
        }
        for m, v in vals.items():
            rows.append({"symbol": symbol, "metric": m, "period_end": pe, "published_at": pub,
                         "value": round(v, 4)})
    for q, (pe, pub) in enumerate([("2025-09-30", "2025-10-21"), ("2025-12-31", "2026-01-21"),
                                    ("2026-03-31", "2026-04-21"), ("2026-06-30", "2026-07-21"),
                                    ("2026-09-30", "2026-10-21")]):
        p = pledge if q == 4 else (pledge_prev if pledge_prev is not None else pledge)
        for m, v in (("promoter_pct", 55.0 + 0.3 * q), ("promoter_pledge_pct", p),
                     ("fii_pct", 18.0 + 0.6 * q), ("dii_pct", 12.0 + 0.4 * q), ("mf_pct", 7.0)):
            rows.append({"symbol": symbol, "metric": m, "period_end": pe, "published_at": pub, "value": v})
    return rows


def prices(symbol: str, start: float, drift: float, end: date = AS_OF, days: int = 2200) -> list[dict]:
    rows = []
    d0 = end - timedelta(days=days)
    for i in range(days + 1):
        d = d0 + timedelta(days=i)
        px = start * (1 + drift) ** i
        rows.append({"date": d.isoformat(), "close": round(px, 2), "volume": 1000 + i % 50})
    return rows


def seed_company(conn, symbol: str, sector: str, industry: str, facts: list[dict],
                 price_rows: list[dict]) -> None:
    import_securities(conn, [{"symbol": symbol, "sector": sector, "industry": industry, "name": symbol.title()}])
    res = import_facts(conn, facts, source="test-export", extracted_by="import")
    assert not res["skipped"], res["skipped"]
    import_prices(conn, price_rows, symbol=symbol, source="test")


def seed_good(conn, symbol="GOODCO"):
    # Strong growth, rising margins, low debt, clean governance; price flat so P/E keeps falling.
    seed_company(conn, symbol, "Industrials", "Capital Goods",
                 annual_facts(symbol, 1000, 0.18, 0.20, 0.01), prices(symbol, 200.0, 0.0))


def seed_bad(conn, symbol="BADCO"):
    # Shrinking revenue, falling margins, heavy debt, 30% pledge, qualified audit, dilution.
    seed_company(conn, symbol, "Industrials", "Capital Goods",
                 annual_facts(symbol, 1000, -0.06, 0.15, -0.015, debt=1500.0, pledge=30.0, pledge_prev=20.0,
                              qualified=1, rpt=25.0, share_growth=0.12),
                 prices(symbol, 50.0, 0.0006))
