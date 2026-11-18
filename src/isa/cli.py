"""Command-line interface. Every command prints JSON so Claude can read it.

    python3 tools/isa.py <command> [options]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from . import audit, service
from .config import ROOT, Config, db_path, load_dotenv
from .engine import scoring
from .importers import broker, classification, facts, market
from .importers.common import ImportError_, load_file, load_records, parse_date
from .report import render
from .storage.db import connect, ensure_security, normalize_symbol
from .tax import build_lots, tax_view

DECISIONS = ("bought", "sold", "trimmed", "added", "held", "ignored", "other")


def _read_input(path: str | None) -> tuple[str, str | None]:
    if path in (None, "-"):
        return sys.stdin.read(), None
    p = Path(path).expanduser()
    return p.read_text(encoding="utf-8-sig"), p.name


def _print(obj) -> None:
    json.dump(obj, sys.stdout, indent=2, default=str, ensure_ascii=False)
    sys.stdout.write("\n")


def _as_of(args) -> date:
    return date.fromisoformat(parse_date(args.as_of)) if getattr(args, "as_of", None) else date.today()


def cmd_init(conn, cfg, args):
    return {"database": str(db_path()), "schema": "ok"}


def _import(conn, kind, fn, args, **kw):
    if args.file not in (None, "-"):
        p = Path(args.file).expanduser()
        records, name = load_file(p), p.name
    else:
        records, name = load_records(sys.stdin.read()), None
    res = fn(conn, records, file_name=name, **kw)
    audit.append(conn, "import", {"kind": kind, "file": name, **{k: v for k, v in kw.items() if k != "as_of"},
                                  "stored": res["stored"], "skipped": len(res.get("skipped", []))})
    conn.commit()
    return res


def cmd_import_holdings(conn, cfg, args):
    return _import(conn, "holdings", broker.import_holdings, args, source=args.source, as_of=args.as_of)


def cmd_import_trades(conn, cfg, args):
    return _import(conn, "trades", broker.import_trades, args, source=args.source, account=args.account)


def cmd_import_prices(conn, cfg, args):
    return _import(conn, "prices", market.import_prices, args, symbol=args.symbol, source=args.source,
                   is_index=args.index)


def cmd_import_securities(conn, cfg, args):
    return _import(conn, "securities", market.import_securities, args)


def cmd_import_facts(conn, cfg, args):
    return _import(conn, "facts", facts.import_facts, args, source=args.source, extracted_by=args.extracted_by)


def cmd_import_classification(conn, cfg, args):
    text, name = _read_input(args.file)
    records = classification.parse_networth(text)
    mapping = load_records(Path(args.map).expanduser().read_text(encoding="utf-8")) if args.map else None
    res = classification.import_classification(conn, records, mapping, file_name=name)
    audit.append(conn, "import", {"kind": "classification", "file": name, "classified": res["classified"],
                                  "unmatched": len(res["unmatched"])})
    conn.commit()
    return res


def cmd_import_indmoney_tax(conn, cfg, args):
    from .importers import indmoney_tax
    p = Path(args.file).expanduser()
    res = indmoney_tax.import_tax_report(conn, p, file_name=p.name)
    audit.append(conn, "import", {"kind": "indmoney_tax_report", "file": p.name, "sales": res["sales_found"],
                                  "stored": res["stored"], "unknown_isins": len(res["unknown_isins"])})
    conn.commit()
    return res


def cmd_import_5paisa_statement(conn, cfg, args):
    from .importers import fivepaisa_tx
    p = Path(args.file).expanduser()
    name_map = Path(args.name_map).expanduser() if args.name_map else ROOT / "data" / "imports" / "name-map.csv"
    res = fivepaisa_tx.import_statement(conn, p, name_map)
    audit.append(conn, "import", {"kind": "fivepaisa_statement", "file": p.name,
                                  **{k: v for k, v in res.items() if k != "unmatched_names"},
                                  "unmatched": len(res["unmatched_names"])})
    conn.commit()
    return res


def cmd_market(conn, cfg, args):
    run = service.run(conn, cfg, _as_of(args), record=False)
    return run["market"]


def cmd_pending_facts(conn, cfg, args):
    return facts.pending_facts(conn, args.symbol)


def cmd_confirm_facts(conn, cfg, args):
    if args.source:
        res = facts.confirm_source(conn, args.source, require_checks=not args.skip_checks)
        conn.commit()
        return res
    if not args.ids:
        raise ValueError("give fact ids or --source DOCUMENT")
    n = facts.confirm_facts(conn, args.ids)
    conn.commit()
    return {"confirmed": n}


def cmd_check_facts(conn, cfg, args):
    issues = facts.check_facts(conn, args.symbol, args.source)
    return {"issues": issues, "passed": not issues}


def cmd_verify_targets(conn, cfg, args):
    from .importers import verify
    return {"targets": verify.verify_targets(conn, args.symbol),
            "denied_sites": sorted(verify.denied_sites())}


def cmd_verify_facts(conn, cfg, args):
    from .importers import verify
    data = json.loads(Path(args.file).expanduser().read_text(encoding="utf-8"))
    readings = data.get("readings", []) if isinstance(data, dict) else data
    res = verify.apply_verifications(conn, readings, cfg.thresholds["verification"])
    conn.commit()
    return res


def cmd_research_targets(conn, cfg, args):
    """Work queue for /research.

    With queries (symbols or company names): those companies. Without: equity
    holdings by weight, then the watchlist. --refresh keeps only stocks that
    have data but may have a newer report.
    """
    from . import coverage
    from .portfolio import portfolio_view
    from .tax import build_lots
    view = portfolio_view(conn, build_lots(conn, cfg.tax), cfg.thresholds)
    weights = {h["symbol"]: h.get("weight") for h in view["holdings"]}
    out, unresolved = [], []
    if args.queries:
        for q in args.queries:
            r = coverage.resolve(conn, q)
            if r["symbol"] is None and r["match"] in ("ambiguous", "none"):
                unresolved.append(r)  # too vague or several matches: ask the user
                continue
            if r["symbol"] is None:  # a company not yet in the database
                out.append({"symbol": None, "name": r["name"], "isin": None, "weight": None, "match": "new",
                            "data": None, "needs": "identify symbol, then full history"})
                continue
            out.append({"symbol": r["symbol"], "name": r["name"], "isin": r["isin"], "match": r["match"]})
    else:
        rows = sorted((h for h in view["holdings"] if not h["is_etf"]), key=lambda h: -(h.get("weight") or 0))
        held = {h["symbol"] for h in rows}
        watch = [r[0] for r in conn.execute("SELECT symbol FROM watchlist ORDER BY symbol")]
        for sym in [h["symbol"] for h in rows] + [s for s in watch if s not in held]:
            sec = conn.execute("SELECT name, isin FROM security WHERE symbol = ?", (sym,)).fetchone()
            out.append({"symbol": sym, "name": sec["name"] if sec else None, "isin": sec["isin"] if sec else None,
                        "match": "portfolio"})
    targets = []
    for t_ in out:
        if t_["symbol"]:
            st = coverage.status(conn, t_["symbol"])
            if args.refresh and st["state"] == "none":
                continue
            t_.update(weight=weights.get(t_["symbol"]), data=st,
                      needs="full history" if st["annual_years"] < 3 else "refresh if a newer report exists")
        elif args.refresh:
            continue
        targets.append(t_)
    if not args.queries:
        targets = targets[: args.top]
    return {"targets": targets, "unresolved": unresolved, "metrics": list(facts.METRICS)}


def cmd_coverage(conn, cfg, args):
    from . import coverage
    from .portfolio import portfolio_view
    from .tax import build_lots
    view = portfolio_view(conn, build_lots(conn, cfg.tax), cfg.thresholds)
    rows = [{"symbol": h["symbol"], "weight": h.get("weight"), **coverage.status(conn, h["symbol"])}
            for h in view["holdings"] if not h["is_etf"]]
    covered = [r for r in rows if r["state"] == "full"]
    return {"equity_holdings": len(rows), "with_full_data": len(covered),
            "value_share_covered": round(sum(r["weight"] or 0 for r in covered), 4),
            "holdings": sorted(rows, key=lambda r: -(r["weight"] or 0))}


def cmd_metrics(conn, cfg, args):
    return {k: {"unit": u, "description": d} for k, (u, d) in facts.METRICS.items()}


def cmd_security(conn, cfg, args):
    sym = normalize_symbol(args.symbol)
    ensure_security(conn, sym, name=args.name, isin=args.isin)
    for key in ("sector", "industry"):
        v = getattr(args, key)
        if v:
            conn.execute(f"UPDATE security SET {key} = ? WHERE symbol = ?", (v, sym))
    conn.commit()
    return dict(conn.execute("SELECT * FROM security WHERE symbol = ?", (sym,)).fetchone())


def cmd_watch(conn, cfg, args):
    if args.action == "list":
        return [dict(r) for r in conn.execute("SELECT * FROM watchlist ORDER BY symbol")]
    sym = normalize_symbol(args.symbol)
    if args.action == "add":
        ensure_security(conn, sym)
        conn.execute("INSERT OR REPLACE INTO watchlist(symbol, added_at, note) VALUES (?, ?, ?)",
                     (sym, date.today().isoformat(), args.note))
    else:
        conn.execute("DELETE FROM watchlist WHERE symbol = ?", (sym,))
    audit.append(conn, "watchlist", {"action": args.action, "note": args.note}, symbol=sym)
    conn.commit()
    return {"symbol": sym, "action": args.action}


def cmd_thesis(conn, cfg, args):
    if args.action == "list":
        q, a = "SELECT * FROM thesis_condition WHERE active = 1", ()
        if args.symbol:
            q, a = q + " AND symbol = ?", (normalize_symbol(args.symbol),)
        return [dict(r) for r in conn.execute(q + " ORDER BY symbol, id", a)]
    if args.action == "retire":
        conn.execute("UPDATE thesis_condition SET active = 0 WHERE id = ?", (args.id,))
        audit.append(conn, "thesis", {"action": "retire", "id": args.id})
        conn.commit()
        return {"retired": args.id}
    sym = normalize_symbol(args.symbol)
    ensure_security(conn, sym)
    cur = conn.execute(
        "INSERT INTO thesis_condition(symbol, metric, op, threshold, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (sym, args.metric, args.op, args.threshold, args.note, date.today().isoformat()))
    audit.append(conn, "thesis", {"action": "add", "id": cur.lastrowid, "metric": args.metric,
                                  "op": args.op, "threshold": args.threshold, "note": args.note}, symbol=sym)
    conn.commit()
    return {"id": cur.lastrowid, "symbol": sym}


def cmd_analyze(conn, cfg, args):
    sym = normalize_symbol(args.symbol)
    run = service.run(conn, cfg, _as_of(args), symbols=[sym], record=not args.no_record)
    sig = run["signals"][0]
    sig["tax_lots"] = [l for l in run["tax"]["lots"] if l["symbol"] == sym]
    return sig


def cmd_portfolio(conn, cfg, args):
    run = service.run(conn, cfg, _as_of(args), record=not args.no_record)
    pv = run["portfolio"]
    return {
        "as_of": run["as_of"], "total_value": pv["total_value"], "top5_weight": pv["top5_weight"],
        "breaches": pv["breaches"], "reconciliation": pv["reconciliation"],
        "missing_price": pv["missing_price"], "unclassified": pv["unclassified"],
        "pending_facts": run["pending_facts"],
        "market": {k: run["market"][k] for k in ("regime", "indices", "breadth", "missing")}
                  | {"sector_leaders": run["market"]["sectors"][:3], "sector_laggards": run["market"]["sectors"][-3:]},
        "asset_classes": pv["asset_classes"], "market_caps": pv["market_caps"],
        "unclassified_assets": pv["unclassified_assets"],
        "holdings": [{k: h[k] for k in ("symbol", "quantity", "avg_cost", "price", "value", "weight",
                                        "unrealised_pct", "sector", "asset_class", "market_cap_bucket",
                                        "accounts", "by_account")} for h in pv["holdings"]],
        "signals": [service.summarize(s) for s in run["signals"]],
        "tax_waits": [l for l in run["tax"]["lots"] if l.get("wait_until")],
    }


def cmd_tax(conn, cfg, args):
    book = build_lots(conn, cfg.tax)
    from .portfolio import latest_prices
    prices = {k: v[0] for k, v in latest_prices(conn).items()}
    return tax_view(book, prices, _as_of(args), cfg.tax, int(cfg.thresholds["tax_view"]["wait_window_days"]))


def cmd_report(conn, cfg, args):
    run = service.run(conn, cfg, _as_of(args), record=not args.no_record)
    out = Path(args.out).expanduser() if args.out else ROOT / "data" / "reports" / f"portfolio-{run['as_of']}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(run), encoding="utf-8")
    return {"report": str(out), "holdings": len(run["portfolio"]["holdings"]), "signals": len(run["signals"])}


def cmd_decision(conn, cfg, args):
    sym = normalize_symbol(args.symbol)
    last = conn.execute("SELECT id, label FROM signal WHERE symbol = ? ORDER BY id DESC LIMIT 1", (sym,)).fetchone()
    eid = audit.append(conn, "decision", {"action": args.action, "note": args.note,
                                          "signal_id": last["id"] if last else None,
                                          "signal_label": last["label"] if last else None}, symbol=sym)
    conn.commit()
    return {"audit_id": eid, "symbol": sym, "action": args.action}


def cmd_audit(conn, cfg, args):
    if args.action == "verify":
        ok, bad = audit.verify(conn)
        return {"ok": ok, "first_bad_id": bad}
    return audit.tail(conn, args.n)


def _fivepaisa_client():
    from .brokers.fivepaisa import FivePaisaClient, Settings
    from .brokers.keychain import SERVICE, Keychain
    return FivePaisaClient(Settings.from_env(), Keychain(os.environ.get("KEYCHAIN_SERVICE") or SERVICE))


def cmd_fivepaisa(conn, cfg, args):
    from .brokers import fivepaisa as fp
    from .brokers.keychain import KeychainError
    try:
        client = _fivepaisa_client()
        if args.action == "status":
            return {"configured": True, "encryption_key_in_keychain": bool(client.store.get(fp.ENCRYPTION_KEY_ITEM)),
                    "response_url": client.s.response_url, **client.token_status()}
        if args.action == "login":
            if args.no_browser:
                state = "manual"
                return {"open_this_url": client.login_url(state),
                        "then": "after login, copy RequestToken from the address bar and run: "
                                "python3 tools/isa.py fivepaisa token  (paste it on stdin)"}
            res = fp.browser_login(client, timeout=args.timeout)
            audit.append(conn, "import", {"kind": "fivepaisa_login", "client_code": res["client_code"]})
            conn.commit()
            return {"logged_in": True, **res}
        if args.action == "token":
            token = sys.stdin.readline().strip()
            if not token:
                raise ValueError("paste the RequestToken on stdin")
            res = client.exchange_request_token(token)
            return {"logged_in": True, **res}
        if args.action == "logout":
            return {"logged_out": client.logout()}
        res = fp.sync(conn, client, prices=not args.no_prices)
        audit.append(conn, "import", {"kind": "fivepaisa_sync", "holdings": res["holdings"],
                                      "trades": res["trades"],
                                      "prices": {k: v for k, v in res["prices"].items() if isinstance(v, int)}})
        conn.commit()
        return res
    except (fp.FivePaisaError, KeychainError) as exc:
        return {"error": str(exc), "session_expired": isinstance(exc, fp.SessionExpired)}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="isa", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create or migrate the database")
    s = sub.add_parser("import-holdings", help="broker holdings JSON/CSV (file or stdin)")
    s.add_argument("--source", required=True, choices=broker.SOURCES)
    s.add_argument("--as-of")
    s.add_argument("--file")
    s = sub.add_parser("import-trades", help="broker trades JSON or tradebook CSV")
    s.add_argument("--source", required=True, choices=broker.SOURCES)
    s.add_argument("--account")
    s.add_argument("--file")
    s = sub.add_parser("import-prices", help="daily candles JSON/CSV")
    s.add_argument("--symbol")
    s.add_argument("--source", required=True)
    s.add_argument("--index", action="store_true", help="the symbol is an index, e.g. 'NIFTY 500'")
    s.add_argument("--file")
    s = sub.add_parser("import-securities", help="symbol, isin, name, exchange, sector, industry CSV")
    s.add_argument("--file")
    s = sub.add_parser("import-facts", help="fundamental/shareholding facts (long format)")
    s.add_argument("--source", required=True, help="e.g. screener-export, annual-report-FY26")
    s.add_argument("--extracted-by", choices=facts.EXTRACTED_BY, default="import")
    s.add_argument("--file")
    s = sub.add_parser("import-classification", help="INDmoney net-worth/holdings reply: asset class, market cap, ETF")
    s.add_argument("--file")
    s.add_argument("--map", help="JSON/CSV of ind_key -> symbol (or isin) from INDmoney's lookup tool")
    s = sub.add_parser("import-indmoney-tax", help="INDmoney consolidated tax report .xlsx: realised stock/ETF sales")
    s.add_argument("--file", required=True)
    s = sub.add_parser("import-5paisa-statement", help="5paisa EQUITY Transaction .xlsx: splits, transfers, demergers, gap trades")
    s.add_argument("--file", required=True)
    s.add_argument("--name-map", help="CSV company_name,symbol for names that don't match (default data/imports/name-map.csv)")
    s = sub.add_parser("market", help="market regime: index trend, India VIX, breadth, sector rotation")
    s.add_argument("--as-of")
    s = sub.add_parser("pending-facts", help="LLM-extracted facts awaiting confirmation")
    s.add_argument("--symbol")
    s = sub.add_parser("confirm-facts", help="confirm pending facts by id, or a whole document with --source")
    s.add_argument("ids", nargs="*", type=int)
    s.add_argument("--source", help="confirm every pending fact from this document (only if checks pass)")
    s.add_argument("--skip-checks", action="store_true")
    s = sub.add_parser("check-facts", help="consistency checks on stored facts")
    s.add_argument("--symbol")
    s.add_argument("--source")
    s = sub.add_parser("verify-targets", help="pending facts for the fact-verifier agent, without their values")
    s.add_argument("--symbol")
    s = sub.add_parser("verify-facts", help="apply independent second readings; confirms matches from another site")
    s.add_argument("--file", required=True)
    s = sub.add_parser("research-targets", help="work queue for /research (by weight, or given symbols/names)")
    s.add_argument("queries", nargs="*", help="symbols or company names, e.g. SANGHVIMOV \"Sanghvi Movers\"")
    s.add_argument("--top", type=int, default=20)
    s.add_argument("--refresh", action="store_true", help="only stocks that already have data")
    s = sub.add_parser("coverage", help="company-data coverage per holding")
    sub.add_parser("metrics", help="list accepted fact metrics")
    s = sub.add_parser("security", help="set sector/industry/name for a stock")
    s.add_argument("symbol")
    s.add_argument("--sector")
    s.add_argument("--industry")
    s.add_argument("--name")
    s.add_argument("--isin")
    s = sub.add_parser("watch")
    s.add_argument("action", choices=("add", "remove", "list"))
    s.add_argument("symbol", nargs="?")
    s.add_argument("--note")
    s = sub.add_parser("thesis")
    s.add_argument("action", choices=("add", "list", "retire"))
    s.add_argument("symbol", nargs="?")
    s.add_argument("metric", nargs="?")
    s.add_argument("op", nargs="?", choices=(">", ">=", "<", "<="))
    s.add_argument("threshold", nargs="?", type=float)
    s.add_argument("--note")
    s.add_argument("--id", type=int)
    for name in ("analyze", "portfolio", "report"):
        s = sub.add_parser(name)
        if name == "analyze":
            s.add_argument("symbol")
        if name == "report":
            s.add_argument("--out")
        s.add_argument("--as-of")
        s.add_argument("--no-record", action="store_true", help="do not store signals")
    s = sub.add_parser("tax")
    s.add_argument("--as-of")
    s = sub.add_parser("decision", help="record what you decided or did")
    s.add_argument("symbol")
    s.add_argument("action", choices=DECISIONS)
    s.add_argument("--note")
    s = sub.add_parser("fivepaisa", help="5paisa read-only API: status, login, token, sync, logout")
    s.add_argument("action", choices=("status", "login", "token", "sync", "logout"))
    s.add_argument("--no-browser", action="store_true", help="print the login URL instead of opening it")
    s.add_argument("--timeout", type=int, default=300, help="seconds to wait for the login redirect")
    s.add_argument("--no-prices", action="store_true", help="skip daily price download")
    s = sub.add_parser("audit")
    s.add_argument("action", choices=("tail", "verify"))
    s.add_argument("-n", type=int, default=20)
    return p


def _validate(args, p: argparse.ArgumentParser) -> None:
    if args.cmd == "watch" and args.action in ("add", "remove") and not args.symbol:
        p.error("watch add/remove needs a symbol")
    if args.cmd == "thesis":
        if args.action == "add" and None in (args.symbol, args.metric, args.op, args.threshold):
            p.error("thesis add SYMBOL METRIC OP THRESHOLD")
        if args.action == "retire" and args.id is None:
            p.error("thesis retire --id N")


def main(argv: list[str] | None = None) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    _validate(args, p)
    load_dotenv()
    cfg = Config.load()
    conn = connect(db_path())
    try:
        handler = globals()["cmd_" + args.cmd.replace("-", "_")]
        result = handler(conn, cfg, args)
        _print(result)
        return 2 if isinstance(result, dict) and "error" in result else 0
    except (ImportError_, ValueError, json.JSONDecodeError, FileNotFoundError) as exc:
        _print({"error": str(exc)})
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
