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
from .importers.common import ImportError_, load_records, parse_date
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
    text, name = _read_input(args.file)
    records = load_records(text)
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


def cmd_market(conn, cfg, args):
    run = service.run(conn, cfg, _as_of(args), record=False)
    return run["market"]


def cmd_pending_facts(conn, cfg, args):
    return facts.pending_facts(conn, args.symbol)


def cmd_confirm_facts(conn, cfg, args):
    n = facts.confirm_facts(conn, args.ids)
    conn.commit()
    return {"confirmed": n}


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
                                        "accounts")} for h in pv["holdings"]],
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
    s = sub.add_parser("market", help="market regime: index trend, India VIX, breadth, sector rotation")
    s.add_argument("--as-of")
    s = sub.add_parser("pending-facts", help="LLM-extracted facts awaiting confirmation")
    s.add_argument("--symbol")
    s = sub.add_parser("confirm-facts")
    s.add_argument("ids", nargs="+", type=int)
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
