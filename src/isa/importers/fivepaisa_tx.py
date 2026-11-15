"""5paisa 'EQUITY Transaction' statement (.xlsx).

Columns: Transaction Date, Company Name, Exchange, Type, Quantity, Price, ..., Remarks.
It has no ISIN or trade numbers, so it is used for what the Trade Listing lacks:
  - Split / Bonus     -> corporate_action (applied to lots in every account)
  - OffMarket-In      -> transfer-in lot: original buy date unknown (held before the transfer)
  - Demerger-In       -> demerger lot: date unknown, cost unknown (apportioned per company notice)
  - Buy/Sell Trade    -> imported only for a (date, stock) the Trade Listing does not already cover
Company names are matched deterministically (exact, unique prefix, unique all-words, or the
user's data/imports/name-map.csv). Anything else is reported, never guessed.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from .broker import _finish_import, _start_import
from .classification import _norm_name
from .common import ImportError_, load_file, parse_date, parse_number

_RATIO = re.compile(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)")


def _name_index(conn: sqlite3.Connection, name_map: dict[str, str]) -> tuple[dict, list]:
    exact: dict[str, set] = {}
    for sym, name in conn.execute("SELECT symbol, name FROM security WHERE is_index = 0 AND name IS NOT NULL AND name != ''"):
        exact.setdefault(_norm_name(name), set()).add(sym)
    return exact, sorted(exact)


def resolve_name(name: str, exact: dict, keys: list, name_map: dict[str, str]) -> str | None:
    if name.strip().lower() in name_map:
        return name_map[name.strip().lower()]
    n = _norm_name(name)
    if not n:
        return None
    hit = exact.get(n)
    if hit and len(hit) == 1:
        return next(iter(hit))
    if len(n) >= 8:  # truncated names: one is a prefix of the other, uniquely
        cands = {s for k in keys if (k.startswith(n) or (len(k) >= 8 and n.startswith(k))) for s in exact[k]}
        if len(cands) == 1:
            return cands.pop()
    words = set(n.split())
    if len(words) >= 2:
        cands = {s for k in keys if words <= set(k.split()) for s in exact[k]}
        if len(cands) == 1:
            return cands.pop()
    return None


def load_name_map(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out = {}
    for r in load_file(path):
        name, sym = (r.get("company_name") or r.get("name") or "").strip(), (r.get("symbol") or "").strip().upper()
        if name and sym:
            out[name.lower()] = sym
    return out


def import_statement(conn: sqlite3.Connection, path, name_map_path: Path | None = None,
                     account: str = "fivepaisa") -> dict:
    p = Path(path)
    name_map = load_name_map(name_map_path) if name_map_path else {}
    exact, keys = _name_index(conn, name_map)
    covered = {(r[0], r[1]) for r in conn.execute(
        "SELECT trade_date, symbol FROM trade WHERE account = ? AND trade_id NOT LIKE '5ptx|%'", (account,))}
    import_id = _start_import(conn, "fivepaisa_statement", "fivepaisa", p.name)
    counts = {"trades": 0, "trades_already_covered": 0, "transfers_in": 0, "demergers": 0, "splits": 0, "duplicates": 0}
    unmatched: dict[str, int] = {}
    seen: dict[str, int] = {}
    for r in load_file(p):
        try:
            d = parse_date(r.get("Transaction Date"))
        except ImportError_:
            continue  # title / footer rows
        name, remark = (r.get("Company Name") or "").strip(), (r.get("Remarks") or "").strip()
        qty, price = parse_number(r.get("Quantity")) or 0.0, parse_number(r.get("Price")) or 0.0
        if qty <= 0 or not name:
            continue
        sym = resolve_name(name, exact, keys, name_map)
        if not sym:
            unmatched[name] = unmatched.get(name, 0) + 1
            continue
        low = remark.lower()
        if low.startswith("split") or low.startswith("bonus"):
            m = _RATIO.search(remark)
            if not m:
                continue
            a_, b_ = float(m.group(1)), float(m.group(2))
            # "Split - 1.00:2.00": 1 old share becomes 2. Bonus "a:b" (format unverified for this
            # statement; none seen yet): a bonus shares per b held -> (a + b) / b.
            ratio = b_ / a_ if low.startswith("split") else (a_ + b_) / b_
            cur = conn.execute("INSERT OR IGNORE INTO corporate_action(symbol, ex_date, kind, ratio, source, note)"
                               " VALUES (?, ?, ?, ?, ?, ?)",
                               (sym, d, "split" if low.startswith("split") else "bonus", ratio, "5paisa-statement", remark))
            counts["splits"] += cur.rowcount
            continue
        if low.startswith("offmarket-in") or low.startswith("demerger-in"):
            kind = "xfer" if low.startswith("offmarket") else "demerger"
            base = f"{kind}|{account}|{sym}|{d}|{qty}"
            seen[base] = seen.get(base, 0) + 1
            cur = conn.execute(
                "INSERT OR IGNORE INTO trade(source, account, trade_id, symbol, side, quantity, price, trade_date, import_id)"
                " VALUES (?, ?, ?, ?, 'BUY', ?, ?, ?, ?)",
                ("fivepaisa", account, f"{base}#{seen[base]}", sym, qty, price if kind == "xfer" else 0.0, d, import_id))
            counts["transfers_in" if kind == "xfer" else "demergers"] += cur.rowcount
            counts["duplicates"] += 0 if cur.rowcount else 1
            continue
        if low in ("buy trade", "sell trade"):
            if (d, sym) in covered:
                counts["trades_already_covered"] += 1
                continue
            side = "BUY" if low == "buy trade" else "SELL"
            base = f"5ptx|{account}|{sym}|{d}|{side}|{qty}|{price}"
            seen[base] = seen.get(base, 0) + 1
            cur = conn.execute(
                "INSERT OR IGNORE INTO trade(source, account, trade_id, symbol, side, quantity, price, trade_date, import_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("fivepaisa", account, f"{base}#{seen[base]}", sym, side, qty, price, d, import_id))
            counts["trades"] += cur.rowcount
            counts["duplicates"] += 0 if cur.rowcount else 1
    _finish_import(conn, import_id, counts["trades"] + counts["transfers_in"] + counts["demergers"] + counts["splits"])
    return {**counts, "unmatched_names": [{"name": k, "rows": v} for k, v in sorted(unmatched.items())]}
