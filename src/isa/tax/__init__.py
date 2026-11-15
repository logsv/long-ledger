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
    # Opening balance: shares held before the earliest imported trade. Their real
    # buy date is unknown (only "before acquired_before") and cost is the broker's average.
    estimated: bool = False
    acquired_before: str | None = None
    cost_known: bool = True  # False for demerger shares (cost apportioned per company notice)
    origin: str = "trade"    # trade | opening | transfer_in | demerger

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
    term: str  # 'STCG' | 'LTCG' | 'unknown'
    estimated: bool = False


@dataclass
class LotBook:
    open_lots: list[Lot] = field(default_factory=list)
    realised: list[Realised] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)  # sells without enough buys


def _splits(conn: sqlite3.Connection) -> dict[str, list[tuple[str, float]]]:
    out: dict[str, list[tuple[str, float]]] = {}
    try:
        rows = conn.execute("SELECT symbol, ex_date, ratio FROM corporate_action ORDER BY ex_date").fetchall()
    except sqlite3.OperationalError:
        return out
    for s, d, r in rows:
        out.setdefault(s, []).append((d, r))
    return out


def _factor_after(splits: list[tuple[str, float]], d: str) -> float:
    """How many current shares one share held on date d has become."""
    f = 1.0
    for ex, r in splits:
        if ex > d:
            f *= r
    return f


def _opening_balances(conn: sqlite3.Connection, symbol: str | None) -> list[Lot]:
    """Shares in each broker's latest snapshot that the imported trades don't explain.

    For a broker with trades starting on date D, the gap (snapshot quantity minus
    net traded quantity) was bought before D. For a broker with no trades at all,
    the whole holding is an opening balance with an unknown date.
    """
    snaps = conn.execute(
        "SELECT h.source, h.symbol, h.quantity, h.avg_price, h.as_of FROM holding_snapshot h JOIN"
        " (SELECT source, MAX(as_of) a FROM holding_snapshot GROUP BY source) m"
        " ON h.source = m.source AND h.as_of = m.a").fetchall()
    # Trades rebuilt from a tax report cover only shares that were sold, so they say
    # nothing about when the remaining shares were bought: they don't set a start date.
    starts = {r[0]: r[1] for r in conn.execute(
        "SELECT account, MIN(trade_date) FROM trade WHERE trade_id NOT LIKE 'indtax|%' GROUP BY account")}
    splits = _splits(conn)
    net: dict[tuple[str, str], float] = {}
    for acct, sym, side, qty, d in conn.execute("SELECT account, symbol, side, quantity, trade_date FROM trade"):
        f = _factor_after(splits.get(sym, []), d)  # express in today's share count
        net[(acct, sym)] = net.get((acct, sym), 0.0) + (qty if side == "BUY" else -qty) * f
    out = []
    for s in snaps:
        if symbol and s["symbol"] != symbol:
            continue
        acct = s["source"]
        gap = s["quantity"] - net.get((acct, s["symbol"]), 0.0)
        if gap <= 1e-6:
            continue
        start = starts.get(acct) or s["as_of"]
        before = date.fromisoformat(start)
        lot_date = (before - timedelta(days=1)).isoformat()
        # Express the lot in the share count of its own date, so pre-split sells match it
        # correctly; later splits then scale it like any other lot.
        f = _factor_after(splits.get(s["symbol"], []), lot_date)
        out.append(Lot(acct, s["symbol"], lot_date, gap / f, (s["avg_price"] or 0.0) * f,
                       estimated=True, acquired_before=before.isoformat(),
                       cost_known=s["avg_price"] is not None, origin="opening"))
    return out


def _term(lot: "Lot", on: date, months: int) -> str:
    if not lot.estimated:
        return "LTCG" if on >= first_long_term_date(date.fromisoformat(lot.buy_date), months) else "STCG"
    # bought at the latest the day before acquired_before
    latest_buy = date.fromisoformat(lot.acquired_before) - timedelta(days=1)
    return "LTCG" if on >= first_long_term_date(latest_buy, months) else "unknown"


def build_lots(conn: sqlite3.Connection, tax_cfg: dict, symbol: str | None = None,
               opening: bool = True) -> LotBook:
    """Match sells to buys FIFO, separately per account (demat).

    With opening=True, each queue starts with an estimated opening lot for shares
    held before the earliest imported trade (see _opening_balances).
    """
    months = int(tax_cfg["long_term_after_months"])
    q = "SELECT account, symbol, side, quantity, price, trade_date, id, trade_id FROM trade"
    args: tuple = ()
    if symbol:
        q += " WHERE symbol = ?"
        args = (symbol,)
    # Same-day: buys before sells, so a same-day round trip matches correctly.
    q += " ORDER BY account, symbol, trade_date, CASE side WHEN 'BUY' THEN 0 ELSE 1 END, id"
    book = LotBook()
    queues: dict[tuple[str, str], list[Lot]] = {}
    if opening:
        for lot in _opening_balances(conn, symbol):
            queues.setdefault((lot.account, lot.symbol), []).append(lot)
    splits = _splits(conn)
    applied: dict[tuple[str, str], set] = {}

    def apply_splits(key: tuple[str, str], up_to: str) -> None:
        """Apply splits with ex_date <= up_to to lots bought before the ex-date."""
        done = applied.setdefault(key, set())
        for ex, r in splits.get(key[1], []):
            if ex <= up_to and ex not in done:
                for lot in queues.get(key, []):
                    if lot.buy_date < ex:
                        lot.quantity *= r
                        lot.cost /= r
                done.add(ex)
    for r in conn.execute(q, args):
        key = (r["account"], r["symbol"])
        queue = queues.setdefault(key, [])
        apply_splits(key, r["trade_date"])
        if r["side"] == "BUY":
            tid = r["trade_id"] or ""
            if tid.startswith("xfer|") or tid.startswith("demerger|"):
                after = (date.fromisoformat(r["trade_date"]) + timedelta(days=1)).isoformat()
                is_xfer = tid.startswith("xfer|")
                new = Lot(r["account"], r["symbol"], r["trade_date"], r["quantity"], r["price"],
                          estimated=True, acquired_before=after,
                          cost_known=is_xfer and r["price"] > 0,
                          origin="transfer_in" if is_xfer else "demerger")
            else:
                new = Lot(r["account"], r["symbol"], r["trade_date"], r["quantity"], r["price"])
            # keep the queue in buy-date order (an opening lot may be dated after some trades)
            pos = len(queue)
            while pos > 0 and queue[pos - 1].buy_date > new.buy_date:
                pos -= 1
            queue.insert(pos, new)
            continue
        remaining = r["quantity"]
        sell_date = date.fromisoformat(r["trade_date"])
        i = 0
        while remaining > 1e-9 and i < len(queue):
            lot = queue[i]
            if lot.buy_date > r["trade_date"]:  # can't sell shares bought later
                break
            take = min(lot.quantity, remaining)
            term = _term(lot, sell_date, months)
            book.realised.append(Realised(
                lot.account, lot.symbol, lot.buy_date, r["trade_date"], take, lot.cost,
                r["price"], round(take * (r["price"] - lot.cost), 2), term, lot.estimated))
            lot.quantity -= take
            remaining -= take
            if lot.quantity <= 1e-9:
                queue.pop(i)
            else:
                i += 1
        if remaining > 1e-9:
            book.errors.append({"account": r["account"], "symbol": r["symbol"],
                                "sell_date": r["trade_date"], "unmatched_quantity": remaining,
                                "reason": "sell without earlier buys: import older tradebooks"})
    for key in queues:
        apply_splits(key, "9999-12-31")
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
        term = _term(lot, today, months)
        is_lt = term == "LTCG"
        if lot.estimated:
            lt_from = None
            days = 0 if is_lt else None
        else:
            lt_from = first_long_term_date(date.fromisoformat(lot.buy_date), months)
            days = 0 if is_lt else (lt_from - today).days
        entry = {**lot.to_dict(), "term_if_sold_today": term,
                 "long_term_from": lt_from.isoformat() if lt_from else None,
                 "days_to_long_term": days, "price": price}
        if price is None:
            entry.update(unrealised_gain=None, est_tax_if_sold=None, note="no price")
        elif not lot.cost_known:
            entry.update(unrealised_gain=None, est_tax_if_sold=None,
                         note=("demerger shares: cost to be apportioned per the company's notice"
                               if lot.origin == "demerger" else "cost unknown"))
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
            elif term == "unknown":
                entry["est_tax_if_sold"] = round(gain * st_rate, 2)
                entry["note"] = (f"bought before {lot.acquired_before}, exact date unknown: shown at STCG "
                                 f"{st_rate:.0%} (worst case); import older tradebooks")
            else:
                entry["est_tax_if_sold"] = round(gain * st_rate, 2)
                if days is not None and days <= wait_window_days:
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
        "estimated_lots": sum(1 for l in book.open_lots if l.estimated),
        "not_modelled": ["loss set-off/carry-forward", "31 Jan 2018 grandfathering",
                         "STT, surcharge, cess"],
    }
