"""Evidence types, point-in-time data access and small numeric helpers."""

from __future__ import annotations

import bisect
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

# Prefer user-entered over imported over (confirmed) LLM-extracted figures.
_SOURCE_RANK = {"user": 0, "import": 1, "llm": 2}


@dataclass
class Evidence:
    key: str            # metric name, usable in thesis conditions
    value: float | None
    points: float | None  # -2..+2, None = informational only
    text: str           # plain-language line, e.g. "ROCE 22.0% (>= 20%)"
    as_of: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BlockResult:
    name: str
    expected: int
    evidence: list[Evidence] = field(default_factory=list)
    veto: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    @property
    def scored(self) -> list[Evidence]:
        return [e for e in self.evidence if e.points is not None]

    @property
    def completeness(self) -> float:
        return min(len(self.scored) / self.expected, 1.0) if self.expected else 0.0

    @property
    def score(self) -> float | None:
        pts = [e.points for e in self.scored]
        if not pts:
            return None
        return max(-2.0, min(2.0, sum(pts) / len(pts)))

    def to_dict(self) -> dict:
        return {"name": self.name, "score": self.score, "completeness": round(self.completeness, 3),
                "evidence": [e.to_dict() for e in self.evidence], "veto": self.veto,
                **({"extra": self.extra} if self.extra else {})}


def band(value: float, cuts: list[tuple[float, float]], floor: float = -2.0) -> float:
    """cuts = [(min_value, points), ...] in descending min_value order."""
    for threshold, points in cuts:
        if value >= threshold:
            return points
    return floor


def cagr(start: float, end: float, years: float) -> float | None:
    if start is None or end is None or start <= 0 or end <= 0 or years <= 0:
        return None
    return ((end / start) ** (1 / years) - 1) * 100


def percentile_rank(value: float, history: list[float]) -> float:
    """Share of history at or below value, 0..100."""
    if not history:
        return 50.0
    below = sum(1 for h in history if h <= value)
    return 100.0 * below / len(history)


def median(xs: list[float]) -> float | None:
    s = sorted(xs)
    if not s:
        return None
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


class Data:
    """Point-in-time view of the database for one evaluation date."""

    def __init__(self, conn: sqlite3.Connection, as_of: date):
        self.conn = conn
        self.as_of = as_of
        self._series_cache: dict[tuple[str, str], list[tuple[str, float, str]]] = {}
        self._price_cache: dict[str, tuple[list[str], list[float], list[float | None]]] = {}

    # ---- facts -------------------------------------------------------------
    def series(self, symbol: str, metric: str) -> list[tuple[str, float, str]]:
        """[(period_end, value, published_at)] known on as_of, oldest first.

        Only facts published on or before as_of and either non-LLM or confirmed.
        One value per period: the best-ranked source, then the latest published.
        """
        key = (symbol, metric)
        if key in self._series_cache:
            return self._series_cache[key]
        rows = self.conn.execute(
            "SELECT period_end, value, published_at, extracted_by FROM fundamental_fact"
            " WHERE symbol = ? AND metric = ? AND published_at <= ?"
            " AND (extracted_by != 'llm' OR confirmed = 1)",
            (symbol, metric, self.as_of.isoformat()),
        ).fetchall()
        best: dict[str, tuple] = {}
        for r in rows:
            rank = (_SOURCE_RANK[r["extracted_by"]], _neg(r["published_at"]))
            cur = best.get(r["period_end"])
            if cur is None or rank < cur[0]:
                best[r["period_end"]] = (rank, r["value"], r["published_at"])
        out = sorted((p, v[1], v[2]) for p, v in best.items())
        self._series_cache[key] = out
        return out

    def latest(self, symbol: str, metric: str) -> tuple[str, float, str] | None:
        s = self.series(symbol, metric)
        return s[-1] if s else None

    def value_years_back(self, symbol: str, metric: str, years: int) -> tuple[str, float] | None:
        """Value for the period about `years` before the latest period."""
        s = self.series(symbol, metric)
        if len(s) < 2:
            return None
        latest = date.fromisoformat(s[-1][0])
        target = latest - timedelta(days=int(365.25 * years) - 45)
        older = [x for x in s if date.fromisoformat(x[0]) <= target]
        if not older:
            return None
        return older[-1][0], older[-1][1]

    def latest_published(self, symbol: str) -> str | None:
        r = self.conn.execute(
            "SELECT MAX(published_at) FROM fundamental_fact WHERE symbol = ? AND published_at <= ?"
            " AND (extracted_by != 'llm' OR confirmed = 1)", (symbol, self.as_of.isoformat())
        ).fetchone()
        return r[0] if r else None

    # ---- prices ------------------------------------------------------------
    def _prices(self, symbol: str):
        if symbol not in self._price_cache:
            rows = self.conn.execute(
                "SELECT date, close, volume FROM price_daily WHERE symbol = ? AND date <= ? ORDER BY date",
                (symbol, self.as_of.isoformat()),
            ).fetchall()
            self._price_cache[symbol] = ([r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows])
        return self._price_cache[symbol]

    def closes(self, symbol: str) -> tuple[list[str], list[float], list[float | None]]:
        return self._prices(symbol)

    def price_on(self, symbol: str, d: str) -> float | None:
        """Last close on or before date d."""
        dates, closes, _ = self._prices(symbol)
        i = bisect.bisect_right(dates, d)
        return closes[i - 1] if i else None

    def last_price(self, symbol: str) -> tuple[float, str] | None:
        """Latest price: the broker's own last price unless a daily close is newer."""
        dates, closes, _ = self._prices(symbol)
        r = self.conn.execute(
            "SELECT last_price, as_of FROM holding_snapshot WHERE symbol = ? AND as_of <= ?"
            " AND last_price IS NOT NULL ORDER BY as_of DESC LIMIT 1",
            (symbol, self.as_of.isoformat()),
        ).fetchone()
        if r and (not dates or r[1] >= dates[-1]):
            return r[0], r[1]
        return (closes[-1], dates[-1]) if dates else None


def _neg(iso: str) -> str:
    """Sort key that orders later dates first."""
    return "".join(chr(255 - ord(c)) for c in iso)
