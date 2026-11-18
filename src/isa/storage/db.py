"""SQLite storage: schema, migrations and connection helper."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 4

# Incremental migrations applied after the v1 SCHEMA, keyed by target version.
MIGRATIONS: dict[int, list[str]] = {
    2: [  # broker-supplied classification (INDmoney)
        "ALTER TABLE security ADD COLUMN asset_class TEXT",        # equity | gold | silver | liquid | ...
        "ALTER TABLE security ADD COLUMN market_cap_bucket TEXT",  # large | mid | small
        "ALTER TABLE security ADD COLUMN is_etf INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE security ADD COLUMN ind_key TEXT",            # INDmoney instrument key
    ],
    3: [  # corporate actions that change share counts (applied to lots in every account)
        """CREATE TABLE IF NOT EXISTS corporate_action (
            id        INTEGER PRIMARY KEY,
            symbol    TEXT NOT NULL,
            ex_date   TEXT NOT NULL,
            kind      TEXT NOT NULL CHECK (kind IN ('split', 'bonus')),
            ratio     REAL NOT NULL CHECK (ratio > 0),   -- new shares per old share, e.g. 2.0 for 1:2
            source    TEXT NOT NULL,
            note      TEXT,
            UNIQUE (symbol, ex_date, kind)
        )""",
    ],
    4: [  # independent second readings of pending facts (fact-verifier agent)
        """CREATE TABLE IF NOT EXISTS fact_verification (
            id          INTEGER PRIMARY KEY,
            fact_id     INTEGER NOT NULL REFERENCES fundamental_fact(id),
            verifier    TEXT NOT NULL,
            value       REAL,
            site        TEXT,              -- registrable domain of the second reading
            source_ref  TEXT,
            verdict     TEXT NOT NULL,     -- match | mismatch | not_found | not_independent | ...
            detail      TEXT,
            verified_at TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_fact_verification_fact ON fact_verification(fact_id)",
    ],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS security (
    symbol    TEXT PRIMARY KEY,
    isin      TEXT,
    name      TEXT,
    exchange  TEXT,
    sector    TEXT,
    industry  TEXT,
    is_index  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS watchlist (
    symbol    TEXT PRIMARY KEY REFERENCES security(symbol),
    added_at  TEXT NOT NULL,
    note      TEXT
);

CREATE TABLE IF NOT EXISTS import_log (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,
    source      TEXT NOT NULL,
    file_name   TEXT,
    rows        INTEGER NOT NULL,
    imported_at TEXT NOT NULL
);

-- Broker holdings as reported on a given date (quantities, average cost).
CREATE TABLE IF NOT EXISTS holding_snapshot (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,
    as_of       TEXT NOT NULL,
    symbol      TEXT NOT NULL REFERENCES security(symbol),
    isin        TEXT,
    quantity    REAL NOT NULL,
    avg_price   REAL,
    last_price  REAL,
    import_id   INTEGER REFERENCES import_log(id),
    UNIQUE (source, as_of, symbol)
);

-- Executed delivery trades. Tax lots are built from these (FIFO per account).
CREATE TABLE IF NOT EXISTS trade (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,
    account     TEXT NOT NULL,
    trade_id    TEXT NOT NULL,
    symbol      TEXT NOT NULL REFERENCES security(symbol),
    isin        TEXT,
    side        TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity    REAL NOT NULL CHECK (quantity > 0),
    price       REAL NOT NULL CHECK (price >= 0),
    trade_date  TEXT NOT NULL,
    import_id   INTEGER REFERENCES import_log(id),
    UNIQUE (source, trade_id)
);

CREATE TABLE IF NOT EXISTS price_daily (
    symbol  TEXT NOT NULL,
    date    TEXT NOT NULL,
    open    REAL,
    high    REAL,
    low     REAL,
    close   REAL NOT NULL,
    volume  REAL,
    source  TEXT NOT NULL,
    PRIMARY KEY (symbol, date)
);

-- One number per (company, metric, period). published_at is the date the
-- figure became public; the engine never uses a fact before that date.
CREATE TABLE IF NOT EXISTS fundamental_fact (
    id            INTEGER PRIMARY KEY,
    symbol        TEXT NOT NULL REFERENCES security(symbol),
    metric        TEXT NOT NULL,
    period_end    TEXT NOT NULL,
    published_at  TEXT NOT NULL,
    value         REAL NOT NULL,
    source        TEXT NOT NULL,
    source_ref    TEXT,
    extracted_by  TEXT NOT NULL CHECK (extracted_by IN ('user', 'import', 'llm')),
    confirmed     INTEGER NOT NULL DEFAULT 0,
    import_id     INTEGER REFERENCES import_log(id),
    UNIQUE (symbol, metric, period_end, source)
);

CREATE TABLE IF NOT EXISTS thesis_condition (
    id          INTEGER PRIMARY KEY,
    symbol      TEXT NOT NULL REFERENCES security(symbol),
    metric      TEXT NOT NULL,
    op          TEXT NOT NULL CHECK (op IN ('>', '>=', '<', '<=')),
    threshold   REAL NOT NULL,
    note        TEXT,
    created_at  TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS signal (
    id              INTEGER PRIMARY KEY,
    symbol          TEXT NOT NULL,
    as_of           TEXT NOT NULL,
    label           TEXT NOT NULL,
    composite       REAL,
    confidence      REAL NOT NULL,
    engine_version  TEXT NOT NULL,
    inputs_hash     TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

-- Append-only, hash-chained audit trail.
CREATE TABLE IF NOT EXISTS audit_event (
    id            INTEGER PRIMARY KEY,
    ts            TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    symbol        TEXT,
    payload_json  TEXT NOT NULL,
    prev_hash     TEXT NOT NULL,
    hash          TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS audit_no_update
BEFORE UPDATE ON audit_event
BEGIN SELECT RAISE(ABORT, 'audit_event is append-only'); END;

CREATE TRIGGER IF NOT EXISTS audit_no_delete
BEFORE DELETE ON audit_event
BEGIN SELECT RAISE(ABORT, 'audit_event is append-only'); END;

CREATE INDEX IF NOT EXISTS idx_fact_symbol_metric ON fundamental_fact(symbol, metric, period_end);
CREATE INDEX IF NOT EXISTS idx_trade_symbol ON trade(account, symbol, trade_date);
CREATE INDEX IF NOT EXISTS idx_signal_symbol ON signal(symbol, as_of);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    """Open the database, creating and migrating it when needed."""
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema v{version} is newer than this code (v{SCHEMA_VERSION})"
        )
    if version == SCHEMA_VERSION:
        return
    if version == 0:
        conn.executescript(SCHEMA)
        version = 1
    for v in range(version + 1, SCHEMA_VERSION + 1):
        for stmt in MIGRATIONS[v]:
            conn.execute(stmt)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


def ensure_security(conn: sqlite3.Connection, symbol: str, **fields) -> None:
    """Insert a security if missing; fill empty fields if given."""
    symbol = normalize_symbol(symbol)
    conn.execute("INSERT OR IGNORE INTO security(symbol) VALUES (?)", (symbol,))
    for key in ("isin", "name", "exchange", "sector", "industry"):
        value = fields.get(key)
        if value:
            conn.execute(
                f"UPDATE security SET {key} = ? WHERE symbol = ? AND ({key} IS NULL OR {key} = '')",
                (value, symbol),
            )
    if fields.get("is_index"):
        conn.execute("UPDATE security SET is_index = 1 WHERE symbol = ?", (symbol,))


def normalize_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    for suffix in ("-EQ", "-BE"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    if not s:
        raise ValueError("empty symbol")
    return s
