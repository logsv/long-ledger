"""Independent cross-verification of pending LLM-extracted facts.

A separate verifier agent reads each pending fact *blind*: verify_targets()
gives it the symbol, metric, unit and period but never the stored value, plus
the website the first reading came from, which the verifier must avoid.

apply_verifications() then decides in code. A pending fact is confirmed only if
all of these hold:
  - the second reading comes from a different website (registrable domain)
    than the first; a fact from model knowledge (origin 'model', no document)
    counts as independent of any real document,
  - neither website is on the settings deny list,
  - the fact has no check_facts issue,
  - the two values agree within [verification] tolerances.
Anything else leaves the fact pending, and the reason is recorded. Every
reading is kept in fact_verification, and every confirmation is audited.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

from ..audit import append, now_utc
from ..storage.db import normalize_symbol
from .facts import FLAG_METRICS, METRICS, PCT_METRICS, check_facts, confirm_facts

ROOT = Path(__file__).resolve().parents[3]
_URL = re.compile(r"https?://[^\s,;)\]]+", re.IGNORECASE)
# Second-level labels under which a registrable domain has three labels (example.co.in).
_SLD = {"co", "gov", "org", "net", "ac", "edu", "res", "nic", "firm", "gen", "ind", "com"}


def site_of(text: str | None) -> str | None:
    """Registrable domain of the first URL in text, e.g. 'ir.srf.com/x.pdf' -> 'srf.com'."""
    if not text:
        return None
    m = _URL.search(text)
    host = urlparse(m.group(0)).hostname if m else None
    if not host:
        return None
    labels = host.lower().rstrip(".").split(".")
    if len(labels) >= 3 and labels[-2] in _SLD and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def denied_sites(settings_paths: list[Path] | None = None) -> set[str]:
    """Domains denied to WebFetch in .claude/settings.json and settings.local.json."""
    paths = settings_paths or [ROOT / ".claude" / "settings.json", ROOT / ".claude" / "settings.local.json"]
    out = set()
    for p in paths:
        try:
            deny = json.loads(p.read_text(encoding="utf-8")).get("permissions", {}).get("deny", [])
        except (OSError, json.JSONDecodeError):
            continue
        for entry in deny:
            m = re.fullmatch(r"WebFetch\(domain:([^)]+)\)", entry)
            if m:
                out.add(m.group(1).lower().removeprefix("www."))
    return out


def _is_denied(site: str | None, denied: set[str]) -> bool:
    return bool(site) and any(site == d or site.endswith("." + d) for d in denied)


def verify_targets(conn: sqlite3.Connection, symbol: str | None = None) -> list[dict]:
    """Pending facts for the verifier, WITHOUT their values."""
    q = ("SELECT f.id, f.symbol, f.metric, f.period_end, f.source, f.source_ref, f.origin, s.name, s.isin"
         " FROM fundamental_fact f LEFT JOIN security s ON s.symbol = f.symbol"
         " WHERE f.confirmed = 0")
    args: tuple = ()
    if symbol:
        q += " AND f.symbol = ?"
        args = (normalize_symbol(symbol),)
    out = []
    for r in conn.execute(q + " ORDER BY f.symbol, f.metric, f.period_end", args):
        tried = [x[0] for x in conn.execute(
            "SELECT DISTINCT site FROM fact_verification WHERE fact_id = ? AND site IS NOT NULL", (r["id"],))]
        out.append({"fact_id": r["id"], "symbol": r["symbol"], "name": r["name"], "isin": r["isin"],
                    "metric": r["metric"], "unit": METRICS[r["metric"]][0],
                    "description": METRICS[r["metric"]][1], "period_end": r["period_end"],
                    "first_origin": r["origin"],
                    "avoid_sites": sorted({s for s in [site_of(r["source_ref"])] + tried if s})})
    return out


def _tolerance(metric: str, value: float, vcfg: dict) -> float:
    if metric in FLAG_METRICS:
        return 0.0
    if metric in PCT_METRICS:
        return float(vcfg["pct_points_tolerance"])
    return max(float(vcfg["rel_tolerance"]) * abs(value), float(vcfg["abs_tolerance"]))


def apply_verifications(conn: sqlite3.Connection, readings: list[dict], vcfg: dict,
                        denied: set[str] | None = None) -> dict:
    """Record verifier readings and confirm the facts that pass every rule."""
    denied = denied_sites() if denied is None else denied
    results = []
    for i, rd in enumerate(readings):
        try:
            fid = int(rd.get("fact_id"))
        except (TypeError, ValueError):
            results.append({"row": i, "verdict": "invalid", "detail": "no fact_id"})
            continue
        fact = conn.execute("SELECT * FROM fundamental_fact WHERE id = ?", (fid,)).fetchone()
        if not fact:
            results.append({"fact_id": fid, "verdict": "invalid", "detail": "unknown fact id"})
            continue
        if fact["confirmed"]:
            results.append({"fact_id": fid, "verdict": "already_confirmed", "detail": ""})
            continue
        url = rd.get("source_url") or rd.get("source_ref")
        site, orig = site_of(url), site_of(fact["source_ref"])
        raw = rd.get("value")
        try:
            value = None if raw is None or raw == "" else float(raw)
        except (TypeError, ValueError):
            value = None
        if value is None:
            verdict, detail = "not_found", rd.get("note") or "verifier found no value"
        elif not site:
            verdict, detail = "no_source", "verifier reading has no source URL"
        elif _is_denied(site, denied) or _is_denied(orig, denied):
            verdict, detail = "denied_source", f"{site if _is_denied(site, denied) else orig} is on the deny list"
        elif not orig and fact["origin"] != "model":
            verdict, detail = "not_independent", "first reading has no source URL to compare against"
        elif site == orig:
            verdict, detail = "not_independent", f"both readings come from {site}"
        else:
            issues = [x["issue"] for x in check_facts(conn, symbol=fact["symbol"]) if x["id"] == fid]
            tol = _tolerance(fact["metric"], fact["value"], vcfg)
            if issues:
                verdict, detail = "check_issue", "; ".join(issues)
            elif abs(value - fact["value"]) <= tol:
                verdict, detail = "match", f"{fact['value']} ({orig or 'model'}) vs {value} ({site}), tolerance {tol:g}"
            else:
                verdict, detail = "mismatch", f"{fact['value']} ({orig or 'model'}) vs {value} ({site}), tolerance {tol:g}"
        conn.execute(
            "INSERT INTO fact_verification(fact_id, verifier, value, site, source_ref, verdict, detail, verified_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (fid, rd.get("verifier") or "fact-verifier", value, site, url, verdict, detail, now_utc()))
        if verdict == "match":
            confirm_facts(conn, [fid])
            append(conn, "fact_verified", {"fact_id": fid, "metric": fact["metric"],
                                           "period_end": fact["period_end"], "value": fact["value"],
                                           "first_site": orig or "model", "second_site": site,
                                           "second_value": value}, symbol=fact["symbol"])
        results.append({"fact_id": fid, "symbol": fact["symbol"], "metric": fact["metric"],
                        "period_end": fact["period_end"], "verdict": verdict, "detail": detail})
    counts: dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {"confirmed": counts.get("match", 0), "counts": counts, "results": results,
            "still_pending": conn.execute("SELECT COUNT(*) FROM fundamental_fact WHERE confirmed = 0").fetchone()[0]}
