"""Broker holdings and trades (MCP JSON output or CSV tradebooks)."""

from __future__ import annotations

import sqlite3
from datetime import date

from ..storage.db import ensure_security, normalize_symbol
from .common import ImportError_, parse_date, parse_number, pick

SOURCES = ("kite", "indmoney", "fivepaisa", "manual")

SYMBOL = ("tradingsymbol", "symbol", "nse_symbol", "ticker", "trading_symbol", "scrip", "ScripName")
ISIN = ("isin",)
NAME = ("name", "company_name", "FullName", "company")
EXCHANGE = ("exchange", "Exch", "exch")
QTY = ("quantity", "qty", "Quantity", "Qty", "total_quantity", "holding_quantity", "units")
T1_QTY = ("t1_quantity",)
AVG = ("average_price", "avg_price", "AvgRate", "buy_avg", "average_buy_price", "avg_cost",
       "buy_price", "Rate", "price")
LAST = ("last_price", "ltp", "CurrentPrice", "current_price", "close_price")
TRADE_ID = ("trade_id", "ExchangeTradeID", "exchange_trade_id", "TradeID")
ORDER_ID = ("order_id", "ExchOrderID")
SIDE = ("transaction_type", "side", "trade_type", "BuySell", "buy_sell", "type")
TRADE_DATE = ("trade_date", "fill_timestamp", "exchange_timestamp", "ExchangeTradeTime",
              "order_execution_time", "order_timestamp", "date", "timestamp")
PRODUCT = ("product", "DelvIntra", "segment")


def _start_import(conn: sqlite3.Connection, kind: str, source: str, file_name: str | None) -> int:
    from ..audit import now_utc
    cur = conn.execute(
        "INSERT INTO import_log(kind, source, file_name, rows, imported_at) VALUES (?, ?, ?, 0, ?)",
        (kind, source, file_name, now_utc()),
    )
    return cur.lastrowid


def _finish_import(conn: sqlite3.Connection, import_id: int, rows: int) -> None:
    conn.execute("UPDATE import_log SET rows = ? WHERE id = ?", (rows, import_id))


def _check_source(source: str) -> None:
    if source not in SOURCES:
        raise ImportError_(f"unknown source {source!r}; expected one of {SOURCES}")


def _side(value) -> str:
    s = str(value or "").strip().upper()
    if s in ("BUY", "B", "BOUGHT"):
        return "BUY"
    if s in ("SELL", "S", "SOLD"):
        return "SELL"
    raise ImportError_(f"unknown trade side: {value!r}")


def _is_delivery(row: dict) -> bool:
    product = pick(row, PRODUCT)
    if product is None:
        return True
    p = str(product).strip().upper()
    # Kite: CNC = delivery; 5paisa: D = delivery; Kite tradebook segment: EQ.
    return p in ("CNC", "D", "EQ", "DELIVERY", "NSE", "BSE")


def import_holdings(conn: sqlite3.Connection, records: list[dict], source: str,
                    as_of: str | None = None, file_name: str | None = None) -> dict:
    """Store a holdings snapshot. Returns counts."""
    _check_source(source)
    as_of = parse_date(as_of) if as_of else date.today().isoformat()
    import_id = _start_import(conn, "holdings", source, file_name)
    stored, skipped = 0, []
    for i, row in enumerate(records):
        try:
            sym_raw = pick(row, SYMBOL)
            if sym_raw is None:
                raise ImportError_("no symbol")
            symbol = normalize_symbol(str(sym_raw))
            qty = parse_number(pick(row, QTY)) or 0.0
            qty += parse_number(pick(row, T1_QTY)) or 0.0
            if qty <= 0:
                raise ImportError_("zero quantity")
            isin = pick(row, ISIN)
            ensure_security(conn, symbol, isin=isin, name=pick(row, NAME),
                            exchange=pick(row, EXCHANGE))
            conn.execute(
                "INSERT INTO holding_snapshot(source, as_of, symbol, isin, quantity, avg_price,"
                " last_price, import_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(source, as_of, symbol) DO UPDATE SET quantity = excluded.quantity,"
                " avg_price = excluded.avg_price, last_price = excluded.last_price,"
                " import_id = excluded.import_id",
                (source, as_of, symbol, isin, qty, parse_number(pick(row, AVG)),
                 parse_number(pick(row, LAST)), import_id),
            )
            stored += 1
        except ImportError_ as exc:
            skipped.append({"row": i, "reason": str(exc)})
    _finish_import(conn, import_id, stored)
    return {"import_id": import_id, "stored": stored, "skipped": skipped, "as_of": as_of}


def import_trades(conn: sqlite3.Connection, records: list[dict], source: str,
                  account: str | None = None, file_name: str | None = None) -> dict:
    """Store delivery trades. Intraday and derivative rows are skipped."""
    _check_source(source)
    account = account or source
    import_id = _start_import(conn, "trades", source, file_name)
    stored, duplicate, skipped = 0, 0, []
    synthetic_seen: dict[str, int] = {}
    for i, row in enumerate(records):
        try:
            if not _is_delivery(row):
                raise ImportError_("not a delivery equity trade")
            sym_raw = pick(row, SYMBOL)
            if sym_raw is None:
                raise ImportError_("no symbol")
            symbol = normalize_symbol(str(sym_raw))
            qty = parse_number(pick(row, QTY))
            price = parse_number(pick(row, AVG))
            if not qty or qty <= 0 or price is None or price < 0:
                raise ImportError_("bad quantity or price")
            side = _side(pick(row, SIDE))
            trade_date = parse_date(pick(row, TRADE_DATE))
            trade_id = pick(row, TRADE_ID)
            if trade_id is None:
                # No exchange trade id: build a key that is stable when the same
                # file is imported again; repeated identical fills get #2, #3...
                base = f"{pick(row, ORDER_ID) or ''}|{symbol}|{trade_date}|{side}|{qty}|{price}"
                synthetic_seen[base] = synthetic_seen.get(base, 0) + 1
                trade_id = f"{base}#{synthetic_seen[base]}"
            isin = pick(row, ISIN)
            ensure_security(conn, symbol, isin=isin, exchange=pick(row, EXCHANGE))
            cur = conn.execute(
                "INSERT OR IGNORE INTO trade(source, account, trade_id, symbol, isin, side,"
                " quantity, price, trade_date, import_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (source, account, str(trade_id), symbol, isin, side, qty, price, trade_date, import_id),
            )
            if cur.rowcount:
                stored += 1
            else:
                duplicate += 1
        except ImportError_ as exc:
            skipped.append({"row": i, "reason": str(exc)})
    _finish_import(conn, import_id, stored)
    return {"import_id": import_id, "stored": stored, "duplicates": duplicate, "skipped": skipped}
