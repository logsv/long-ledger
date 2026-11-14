"""FIFO tax lots and STCG/LTCG view for listed equity (STT paid).

Rules come from config/tax.toml (Income-tax Act, 2025, s.196 / s.198).
Not modelled: loss set-off and carry-forward, 31 Jan 2018 grandfathering,
STT, surcharge and cess. Figures are gross estimates, not tax advice.
"""

from __future__ import annotations

import calendar
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta


def add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def first_long_term_date(buy: date, months: int) -> date:
    """Held 'more than' N months: long-term from the day after the anniversary."""
    return add_months(buy, months) + timedelta(days=1)


def fy_start(d: date, start_month: int = 4) -> date:
    return date(d.year if d.month >= start_month else d.year - 1, start_month, 1)


@dataclass
class Lot:
    account: str
    symbol: str
    buy_date: str
    quantity: float
    cost: float  # per share

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Realised:
    account: str
    symbol: str
    buy_date: str
    sell_date: str
    quantity: float
    cost: float
    proceeds: float
    gain: float
    term: str  # 'STCG' | 'LTCG'


@dataclass
class LotBook:
    open_lots: list[Lot] = field(default_factory=list)
    realised: list[Realised] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)  # sells without enough buys


def build_lots(conn: sqlite3.Connection, tax_cfg: dict, symbol: str | None = None) -> LotBook:
    """Match sells to buys FIFO, separately per account (demat)."""
    months = int(tax_cfg["long_term_after_months"])
    q = "SELECT account, symbol, side, quantity, price, trade_date, id FROM trade"
    args: tuple = ()
    if symbol:
        q += " WHERE symbol = ?"
        args = (symbol,)
    # Same-day: buys before sells, so a same-day round trip matches correctly.
    q += " ORDER BY account, symbol, trade_date, CASE side WHEN 'BUY' THEN 0 ELSE 1 END, id"
    book = LotBook()
    queues: dict[tuple[str, str], list[Lot]] = {}
    for r in conn.execute(q, args):
        key = (r["account"], r["symbol"])
        queue = queues.setdefault(key, [])
        if r["side"] == "BUY":
            queue.append(Lot(r["account"], r["symbol"], r["trade_date"], r["quantity"], r["price"]))
            continue
        remaining = r["quantity"]
        sell_date = date.fromisoformat(r["trade_date"])
        while remaining > 1e-9 and queue:
            lot = queue[0]
            take = min(lot.quantity, remaining)
            buy = date.fromisoformat(lot.buy_date)
            term = "LTCG" if sell_date >= first_long_term_date(buy, months) else "STCG"
            book.realised.append(Realised(
                lot.account, lot.symbol, lot.buy_date, r["trade_date"], take, lot.cost,
                r["price"], round(take * (r["price"] - lot.cost), 2), term))
            lot.quantity -= take
            remaining -= take
            if lot.quantity <= 1e-9:
                queue.pop(0)
        if remaining > 1e-9:
            book.errors.append({"account": r["account"], "symbol": r["symbol"],
                                "sell_date": r["trade_date"], "unmatched_quantity": remaining,
                                "reason": "sell without earlier buys: import older tradebooks"})
    for queue in queues.values():
        book.open_lots.extend(lot for lot in queue if lot.quantity > 1e-9)
    return book


def ltcg_used_this_fy(book: LotBook, today: date, tax_cfg: dict) -> float:
    start = fy_start(today, int(tax_cfg["fy_start_month"])).isoformat()
    total = sum(r.gain for r in book.realised if r.term == "LTCG" and r.sell_date >= start
                and r.sell_date <= today.isoformat())
    return max(total, 0.0)


def tax_view(book: LotBook, prices: dict[str, float], today: date, tax_cfg: dict,
             wait_window_days: int) -> dict:
    """Per-lot unrealised gains, term, days to long-term and a sell-now estimate."""
    months = int(tax_cfg["long_term_after_months"])
    st_rate = float(tax_cfg["stcg"]["rate"])
    lt_rate = float(tax_cfg["ltcg"]["rate"])
    exemption = float(tax_cfg["ltcg"]["annual_exemption"])
    used = ltcg_used_this_fy(book, today, tax_cfg)
    remaining_exemption = max(exemption - used, 0.0)
    lots = []
    for lot in sorted(book.open_lots, key=lambda x: (x.symbol, x.buy_date)):
        price = prices.get(lot.symbol)
        buy = date.fromisoformat(lot.buy_date)
        lt_from = first_long_term_date(buy, months)
        is_lt = today >= lt_from
        entry = {**lot.to_dict(), "term_if_sold_today": "LTCG" if is_lt else "STCG",
                 "long_term_from": lt_from.isoformat(),
                 "days_to_long_term": 0 if is_lt else (lt_from - today).days,
                 "price": price}
        if price is None:
            entry.update(unrealised_gain=None, est_tax_if_sold=None, note="no price")
        else:
            gain = round(lot.quantity * (price - lot.cost), 2)
            entry["unrealised_gain"] = gain
            if gain <= 0:
                entry["est_tax_if_sold"] = 0.0
                entry["note"] = "loss: set-off not modelled"
            elif is_lt:
                taxable = max(gain - remaining_exemption, 0.0)
                entry["est_tax_if_sold"] = round(taxable * lt_rate, 2)
                entry["note"] = f"LTCG {lt_rate:.1%} above remaining exemption"
            else:
                entry["est_tax_if_sold"] = round(gain * st_rate, 2)
                if entry["days_to_long_term"] <= wait_window_days:
                    entry["note"] = (f"turns long-term on {lt_from.isoformat()}: waiting saves"
                                     f" about {round(gain * st_rate - max(gain - remaining_exemption, 0) * lt_rate, 2)}")
                    entry["wait_until"] = lt_from.isoformat()
                else:
                    entry["note"] = f"STCG {st_rate:.0%}"
        lots.append(entry)
    return {
        "act": tax_cfg["act"],
        "sources": {"stcg": tax_cfg["stcg"]["source"], "ltcg": tax_cfg["ltcg"]["source"]},
        "ltcg_exemption": exemption,
        "ltcg_realised_this_fy": round(used, 2),
        "ltcg_exemption_remaining": round(remaining_exemption, 2),
        "lots": lots,
        "unmatched_sells": book.errors,
        "not_modelled": ["loss set-off/carry-forward", "31 Jan 2018 grandfathering",
                         "STT, surcharge, cess"],
    }
