"""Shared parsing helpers for importers."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

_MS_DATE = re.compile(r"/Date\((-?\d+)([+-]\d{4})?\)/")
_DATE_FORMATS = (
    "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y",
    "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y", "%Y/%m/%d", "%d-%m-%Y %H:%M:%S",
)


class ImportError_(ValueError):
    """Raised when input data cannot be imported safely."""


def parse_date(value: Any) -> str:
    """Return an ISO date (YYYY-MM-DD) from the common broker formats."""
    if value is None or value == "":
        raise ImportError_("missing date")
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    s = str(value).strip()
    m = _MS_DATE.fullmatch(s)
    if m:  # 5paisa style /Date(1699999999000+0530)/
        ms = int(m.group(1))
        tz = m.group(2)
        offset = timedelta(hours=5, minutes=30)
        if tz:
            sign = 1 if tz[0] == "+" else -1
            offset = sign * timedelta(hours=int(tz[1:3]), minutes=int(tz[3:5]))
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone(offset))
        return dt.date().isoformat()
    if "T" in s and ("+" in s[10:] or s.endswith("Z")):
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).date().isoformat()
    except ValueError as exc:
        raise ImportError_(f"unrecognised date: {s!r}") from exc


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ImportError_("boolean is not a number")
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "").replace("₹", "").replace("%", "")
    if s in ("", "-", "NA", "N/A", "null", "None"):
        return None
    try:
        return float(s)
    except ValueError as exc:
        raise ImportError_(f"not a number: {value!r}") from exc


def pick(row: dict, aliases: Iterable[str]) -> Any:
    """First non-empty value among aliases (case-insensitive keys)."""
    lowered = {str(k).lower(): v for k, v in row.items()}
    for key in aliases:
        v = lowered.get(key.lower())
        if v not in (None, ""):
            return v
    return None


def load_records(text: str) -> list[dict]:
    """Parse JSON (list, or object wrapping a list) or CSV text into dict rows."""
    text = text.strip().lstrip("﻿")
    if not text:
        return []
    if text[0] in "[{":
        data = json.loads(text)
        return _unwrap(data)
    reader = csv.DictReader(io.StringIO(text))
    return [dict(r) for r in reader]


def _unwrap(data: Any) -> list[dict]:
    if isinstance(data, list):
        if all(isinstance(r, dict) for r in data):
            return data
        if all(isinstance(r, list) for r in data):  # raw candles
            return data  # type: ignore[return-value]
        raise ImportError_("expected a list of objects")
    if isinstance(data, dict):
        for key in ("data", "Data", "holdings", "Holdings", "trades", "TradeBookDetail",
                    "TradeBook", "candles", "body", "result", "records", "facts", "net"):
            if key in data:
                return _unwrap(data[key])
        lists = [v for v in data.values() if isinstance(v, list)]
        if len(lists) == 1:
            return _unwrap(lists[0])
        if all(not isinstance(v, (list, dict)) for v in data.values()):
            return [data]
    raise ImportError_("could not find a list of records in the JSON")
