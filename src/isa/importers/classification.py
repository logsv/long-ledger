"""Asset class, market-cap bucket and ETF flag from INDmoney's MCP output.

INDmoney's net-worth/holdings reply lists every holding across linked brokers
with `investment_code` (an INDmoney key such as INDS19182), `investment` (name),
`assetclass_l2` (equity/gold/silver/liquid) and `market_cap` (large/mid/small).
It carries no trading symbol, so rows are matched to our securities by:
  1. a stored ind_key, 2. a mapping file {ind_key, symbol|isin} (built with
  INDmoney's lookup tool), 3. an exact normalised company-name match.
Unmatched rows are reported, never guessed.
"""

from __future__ import annotations

import json
import re
import sqlite3

from ..storage.db import ensure_security, normalize_symbol
from .broker import _finish_import, _start_import
from .common import ImportError_, pick

_SUFFIX = re.compile(r"\b(limited|ltd|ltd\.|the|inc)\b\.?", re.IGNORECASE)
ETF_HINT = re.compile(r"\b(etf|bees)\b", re.IGNORECASE)
NON_EQUITY = {"gold", "silver", "liquid", "debt", "commodity"}
BUCKETS = {"large", "mid", "small"}


def _norm_name(name: str | None) -> str:
    s = _SUFFIX.sub(" ", (name or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def parse_networth(text: str) -> list[dict]:
    """Accept the raw MCP reply (optionally wrapped in {"result": "<json>"}) or a plain list."""
    data = json.loads(text)
    if isinstance(data, dict) and isinstance(data.get("result"), str):
        data = json.loads(data["result"])
    if isinstance(data, dict):
        data = data.get("holdings", data.get("data"))
    if not isinstance(data, list):
        raise ImportError_("no holdings list found in the INDmoney reply")
    return [r for r in data if isinstance(r, dict)]


def import_classification(conn: sqlite3.Connection, records: list[dict], mapping: list[dict] | None = None,
                          file_name: str | None = None) -> dict:
    import_id = _start_import(conn, "classification", "indmoney", file_name)
    by_key = {r["ind_key"]: r["symbol"] for r in conn.execute(
        "SELECT ind_key, symbol FROM security WHERE ind_key IS NOT NULL")}
    by_isin = {r["isin"]: r["symbol"] for r in conn.execute(
        "SELECT isin, symbol FROM security WHERE isin IS NOT NULL AND isin != ''")}
    by_name: dict[str, list[str]] = {}
    for r in conn.execute("SELECT symbol, name FROM security WHERE name IS NOT NULL AND name != ''"):
        by_name.setdefault(_norm_name(r["name"]), []).append(r["symbol"])
    for m in mapping or []:
        key = pick(m, ("ind_key", "investment_code"))
        sym = pick(m, ("symbol", "tradingsymbol"))
        isin = pick(m, ("isin",))
        if key and sym:
            by_key[key] = normalize_symbol(sym)
        elif key and isin and isin in by_isin:
            by_key[key] = by_isin[isin]

    stored, unmatched, seen = 0, [], set()
    for row in records:
        key = pick(row, ("investment_code", "ind_key"))
        name = pick(row, ("investment", "name"))
        sym = by_key.get(key) if key else None
        if not sym:
            isin = pick(row, ("isin",))
            sym = by_isin.get(isin) if isin else None
        if not sym:
            cands = by_name.get(_norm_name(name), [])
            sym = cands[0] if len(cands) == 1 else None
        if not sym:
            if key not in seen:
                unmatched.append({"ind_key": key, "name": name})
                seen.add(key)
            continue
        if sym in seen:
            continue
        seen.add(sym)
        asset = str(pick(row, ("assetclass_l2", "asset_class")) or "").strip().lower() or None
        bucket = str(pick(row, ("market_cap", "market_cap_bucket")) or "").strip().lower() or None
        is_etf = 1 if (asset in NON_EQUITY or ETF_HINT.search(name or "")) else 0
        if is_etf or bucket not in BUCKETS:
            bucket = None  # a market-cap bucket is meaningless for ETFs
        ensure_security(conn, sym)
        conn.execute(
            "UPDATE security SET asset_class = ?, market_cap_bucket = ?, is_etf = ?,"
            " ind_key = COALESCE(?, ind_key), name = COALESCE(NULLIF(name, ''), ?) WHERE symbol = ?",
            (asset, bucket, is_etf, key, name, sym))
        stored += 1
    _finish_import(conn, import_id, stored)
    return {"import_id": import_id, "classified": stored, "unmatched": unmatched}
