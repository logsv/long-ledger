"""INDmoney 'consolidated tax report' (.xlsx): realised Indian equity and ETF sales.

Each row of the Indian Stocks / ETF sections in the LTCG and STCG sheets is a
matched sale: purchase date and price, redemption date and price, units. It is
turned into one BUY and one SELL trade for the INDmoney demat, so those lots
get exact dates. Only INDmoney-held shares are covered (the report says so).

Privacy: only the section rows are read. The header (client name, PAN) and the
other sheets (mutual funds, US stocks, Schedule FA, foreign income) are ignored.
"""

from __future__ import annotations

import re
import sqlite3

from .broker import import_trades
from .common import ImportError_, _xlsx_rows, parse_date, parse_number, xlsx_sheet_names

SECTIONS = {"indian stocks", "equity etfs", "non - equity etfs", "non-equity etfs"}
STOP = {"equity mutual funds", "non - equity mutual funds", "non-equity mutual funds", "us stocks",
        "rights entitlements", "stcg - buyback", "ltcg - buyback", "notes:"}
_ISIN = re.compile(r"IN[EF][A-Z0-9]{9}")


def extract(path) -> list[dict]:
    names = xlsx_sheet_names(path)
    out: list[dict] = []
    for sheet in ("LTCG", "STCG"):
        if sheet not in names:
            continue
        rows = _xlsx_rows(path, sheet)
        in_section, cols = False, None
        for r in rows:
            cells = [c.strip() for c in r]
            first = next((c for c in cells if c), "").lower()
            if first in SECTIONS:
                in_section, cols = True, None
                continue
            if first in STOP or first.startswith("ltcg - ") or first.startswith("stcg - "):
                in_section, cols = False, None
                continue
            if not in_section:
                continue
            if "Name of Stock" in cells and "ISIN" in cells and "Units sold" in cells:
                cols = {name: i for i, name in enumerate(cells) if name}
                continue
            if cols is None:
                continue
            isin = cells[cols["ISIN"]] if cols["ISIN"] < len(cells) else ""
            if not _ISIN.fullmatch(isin):
                continue  # 'Gains' / 'Losses' / '-' / totals
            u = cols["Units sold"]
            try:
                out.append({
                    "name": cells[cols["Name of Stock"]], "isin": isin, "sheet": sheet,
                    "sell_date": parse_date(cells[cols["Redemption date"]]),
                    "buy_date": parse_date(cells[cols["Purchase date"]]),
                    "units": parse_number(cells[u]),
                    "sell_price": parse_number(cells[u + 1]),   # 'Per unit' -> Sell Value
                    "buy_price": parse_number(cells[u + 2]),    #            -> Purchase Value
                })
            except (ImportError_, IndexError) as exc:
                raise ImportError_(f"unexpected row layout in {sheet}: {exc}") from exc
    return out


def import_tax_report(conn: sqlite3.Connection, path, file_name: str | None = None) -> dict:
    sales = extract(path)
    trades = []
    for i, s in enumerate(sales):
        if not s["units"] or s["units"] <= 0:
            continue
        key = f"indtax|{s['isin']}|{s['buy_date']}|{s['sell_date']}|{s['units']}|{s['buy_price']}|{s['sell_price']}"
        common = {"isin": s["isin"], "Scrip Name": s["name"], "quantity": s["units"]}
        trades.append({**common, "trade_type": "buy", "price": s["buy_price"], "trade_date": s["buy_date"],
                       "trade_id": key + "|B"})
        trades.append({**common, "trade_type": "sell", "price": s["sell_price"], "trade_date": s["sell_date"],
                       "trade_id": key + "|S"})
    res = import_trades(conn, trades, "indmoney", file_name=file_name)
    res["sales_found"] = len(sales)
    return res
