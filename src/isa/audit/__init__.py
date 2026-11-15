"""Append-only, hash-chained audit log."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

GENESIS = "0" * 64

EVENT_TYPES = {
    "import",           # records or facts loaded
    "fact_confirmed",   # user confirmed an LLM-extracted fact
    "signal",           # engine produced a label
    "decision",         # user recorded what they decided / did
    "thesis",           # thesis condition added or retired
    "watchlist",        # watchlist change
    "blocked_tool",     # an order tool call was refused
    "ui_action",        # a button pressed in the local dashboard
}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(prev_hash: str, ts: str, event_type: str, symbol: str | None, payload: str) -> str:
    raw = "\x1f".join([prev_hash, ts, event_type, symbol or "", payload])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def append(conn: sqlite3.Connection, event_type: str, payload: dict,
           symbol: str | None = None, ts: str | None = None) -> int:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown audit event type: {event_type}")
    ts = ts or now_utc()
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    row = conn.execute("SELECT hash FROM audit_event ORDER BY id DESC LIMIT 1").fetchone()
    prev = row[0] if row else GENESIS
    h = _digest(prev, ts, event_type, symbol, body)
    cur = conn.execute(
        "INSERT INTO audit_event(ts, event_type, symbol, payload_json, prev_hash, hash)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (ts, event_type, symbol, body, prev, h),
    )
    return cur.lastrowid


def verify(conn: sqlite3.Connection) -> tuple[bool, int | None]:
    """Recompute the chain. Returns (ok, first_bad_id)."""
    prev = GENESIS
    for r in conn.execute(
        "SELECT id, ts, event_type, symbol, payload_json, prev_hash, hash FROM audit_event ORDER BY id"
    ):
        if r["prev_hash"] != prev:
            return False, r["id"]
        if _digest(prev, r["ts"], r["event_type"], r["symbol"], r["payload_json"]) != r["hash"]:
            return False, r["id"]
        prev = r["hash"]
    return True, None


def tail(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT id, ts, event_type, symbol, payload_json FROM audit_event ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {"id": r["id"], "ts": r["ts"], "event_type": r["event_type"],
         "symbol": r["symbol"], "payload": json.loads(r["payload_json"])}
        for r in rows
    ]
