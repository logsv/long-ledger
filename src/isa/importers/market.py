"""Daily prices and the security master."""

from __future__ import annotations

import sqlite3

from ..storage.db import ensure_security, normalize_symbol
from .broker import _finish_import, _start_import
from .common import ImportError_, parse_date, parse_number, pick


def import_prices(conn: sqlite3.Connection, records: list[dict], symbol: str | None,
                  source: str, file_name: str | None = None, is_index: bool = False) -> dict:
    """Store daily candles. Rows may carry their own symbol column."""
    import_id = _start_import(conn, "prices", source, file_name)
    stored, skipped = 0, []
    for i, row in enumerate(records):
        try:
            if isinstance(row, list):  # raw candle [date, o, h, l, c, v]
                row = dict(zip(("date", "open", "high", "low", "close", "volume"), row))
            sym = symbol or pick(row, ("symbol", "tradingsymbol"))
            if not sym:
                raise ImportError_("no symbol (pass --symbol)")
            sym = sym.strip().upper() if is_index else normalize_symbol(sym)
            close = parse_number(pick(row, ("close", "Close", "close_price", "ltp")))
            if close is None or close <= 0:
                raise ImportError_("bad close")
            d = parse_date(pick(row, ("date", "Date", "timestamp", "Datetime")))
            ensure_security(conn, sym, is_index=is_index)
            conn.execute(
                "INSERT INTO price_daily(symbol, date, open, high, low, close, volume, source)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(symbol, date) DO UPDATE SET"
                " open = excluded.open, high = excluded.high, low = excluded.low,"
                " close = excluded.close, volume = excluded.volume, source = excluded.source",
                (sym, d, parse_number(pick(row, ("open", "Open"))),
                 parse_number(pick(row, ("high", "High"))), parse_number(pick(row, ("low", "Low"))),
                 close, parse_number(pick(row, ("volume", "Volume"))), source),
            )
            stored += 1
        except ImportError_ as exc:
            skipped.append({"row": i, "reason": str(exc)})
    _finish_import(conn, import_id, stored)
    return {"import_id": import_id, "stored": stored, "skipped": skipped}


def import_securities(conn: sqlite3.Connection, records: list[dict], file_name: str | None = None) -> dict:
    """Security master: symbol, isin, name, exchange, sector, industry.

    Sector and industry are overwritten here (this file is the user's own
    classification), unlike broker imports which only fill blanks.
    """
    import_id = _start_import(conn, "securities", "manual", file_name)
    stored, skipped = 0, []
    for i, row in enumerate(records):
        try:
            sym = pick(row, ("symbol", "tradingsymbol"))
            if not sym:
                raise ImportError_("no symbol")
            sym = normalize_symbol(sym)
            ensure_security(conn, sym, isin=pick(row, ("isin",)), name=pick(row, ("name",)),
                            exchange=pick(row, ("exchange",)))
            for key in ("sector", "industry"):
                value = pick(row, (key,))
                if value:
                    conn.execute(f"UPDATE security SET {key} = ? WHERE symbol = ?", (value.strip(), sym))
            stored += 1
        except ImportError_ as exc:
            skipped.append({"row": i, "reason": str(exc)})
    _finish_import(conn, import_id, stored)
    return {"import_id": import_id, "stored": stored, "skipped": skipped}
