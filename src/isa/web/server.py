"""Standard-library HTTP server for the local dashboard.

Security:
- Listens on the loopback address 127.0.0.1 only (never all interfaces) and rejects other Host headers
  (protects against DNS-rebinding pages in your browser).
- Data endpoints open SQLite read-only.
- Actions (POST) need the per-run token embedded in the page and a matching
  Origin, so other websites can't trigger them.
- No order endpoints exist. Actions: refresh, recompute, report, fivepaisa_sync.
- Strict Content-Security-Policy: only this server's own scripts run.
"""

from __future__ import annotations

import json
import mimetypes
import secrets
import sqlite3
import threading
import webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .. import audit, service
from ..config import ROOT, Config, db_path, load_dotenv
from ..report import render
from ..storage.db import connect
from . import api

HOST = "127.0.0.1"
DEFAULT_PORT = 8770
STATIC = Path(__file__).resolve().parent / "static"
ACTIONS = ("refresh", "recompute", "report", "fivepaisa_sync")
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


class Dashboard:
    def __init__(self, database: Path | None = None, config: Config | None = None):
        self.db = Path(database or db_path())
        self.cfg = config or Config.load()
        self.token = secrets.token_urlsafe(24)
        self._lock = threading.Lock()
        self._run: dict | None = None
        self.computed_at: str | None = None
        conn = connect(self.db)  # create / migrate once, read-write
        conn.close()

    # ---- data ----------------------------------------------------------------
    def ro(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def run(self, refresh: bool = False) -> dict:
        with self._lock:
            if self._run is None or refresh:
                conn = self.ro()
                try:
                    self._run = service.run(conn, self.cfg, date.today(), record=False)
                finally:
                    conn.close()
                self.computed_at = datetime.now().isoformat(timespec="seconds")
            return self._run

    def view(self, name: str) -> object:
        run = self.run()
        if name == "overview":
            conn = self.ro()
            try:
                return {**api.overview(run, conn), "computed_at": self.computed_at}
            finally:
                conn.close()
        if name == "holdings":
            return api.holdings(run)
        if name == "lots":
            return api.lots(run)
        conn = self.ro()
        try:
            if name == "trades":
                return api.trades(conn)
            if name == "quality":
                return api.quality(run, conn)
        finally:
            conn.close()
        raise KeyError(name)

    # ---- actions -------------------------------------------------------------
    def action(self, name: str) -> dict:
        if name not in ACTIONS:
            raise KeyError(name)
        if name == "refresh":
            self.run(refresh=True)
            return {"ok": True, "message": f"Data reloaded at {self.computed_at}"}
        conn = connect(self.db)
        try:
            if name == "recompute":
                res = service.run(conn, self.cfg, date.today(), record=True)
                msg = f"Recomputed and stored {len(res['signals'])} signals"
            elif name == "report":
                res = service.run(conn, self.cfg, date.today(), record=False)
                out = ROOT / "data" / "reports" / f"portfolio-{res['as_of']}.html"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(render(res), encoding="utf-8")
                msg = f"Report written to {out}"
            else:
                msg = self._fivepaisa_sync(conn)
            audit.append(conn, "ui_action", {"action": name, "result": msg})
            conn.commit()
        finally:
            conn.close()
        self.run(refresh=True)
        return {"ok": True, "message": msg}

    def _fivepaisa_sync(self, conn: sqlite3.Connection) -> str:
        from ..brokers import fivepaisa as fp
        from ..brokers.keychain import Keychain
        load_dotenv()
        client = fp.FivePaisaClient(fp.Settings.from_env(), Keychain())
        if not client.token_status().get("logged_in"):
            raise fp.SessionExpired("5paisa is not logged in today: run `python3 tools/isa.py fivepaisa login`")
        res = fp.sync(conn, client)
        audit.append(conn, "import", {"kind": "fivepaisa_sync", "holdings": res["holdings"], "trades": res["trades"]})
        return f"5paisa: {res['holdings']} holdings, {res['trades']} new trades"


def make_handler(dash: Dashboard, port: int):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    allowed_origins = {f"http://{h}" for h in allowed_hosts}

    class Handler(BaseHTTPRequestHandler):
        server_version = "isa-dashboard"
        sys_version = ""

        def log_message(self, *args):  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str, cache: bool = False) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj, default=str).encode(), "application/json; charset=utf-8")

        def _host_ok(self) -> bool:
            if self.headers.get("Host") not in allowed_hosts:
                self._json(421, {"error": "unexpected Host header"})
                return False
            return True

        def do_GET(self):  # noqa: N802
            if not self._host_ok():
                return
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                html = (STATIC / "index.html").read_text(encoding="utf-8").replace("{{TOKEN}}", dash.token)
                return self._send(200, html.encode(), "text/html; charset=utf-8")
            if path.startswith("/static/"):
                target = (STATIC / path[len("/static/"):]).resolve()
                if STATIC not in target.parents or not target.is_file():
                    return self._json(404, {"error": "not found"})
                ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype in ("application/javascript",):
                    ctype += "; charset=utf-8"
                return self._send(200, target.read_bytes(), ctype, cache="/vendor/" in path)
            if path.startswith("/api/"):
                try:
                    return self._json(200, dash.view(path[len("/api/"):]))
                except KeyError:
                    return self._json(404, {"error": "unknown view"})
                except Exception as exc:  # report, don't crash the server
                    return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
            self._json(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if not self._host_ok():
                return
            origin = self.headers.get("Origin")
            if origin is not None and origin not in allowed_origins:
                return self._json(403, {"error": "cross-origin request refused"})
            if not secrets.compare_digest(self.headers.get("X-ISA-Token", ""), dash.token):
                return self._json(403, {"error": "missing or wrong token"})
            path = urlparse(self.path).path
            if not path.startswith("/api/action/"):
                return self._json(404, {"error": "not found"})
            name = path[len("/api/action/"):]
            if name not in ACTIONS:
                return self._json(404, {"error": f"unknown action {name!r}"})
            try:
                return self._json(200, dash.action(name))
            except Exception as exc:
                return self._json(400, {"ok": False, "message": f"{type(exc).__name__}: {exc}"})

        def do_PUT(self):  # noqa: N802
            self._json(405, {"error": "method not allowed"})

        do_DELETE = do_PATCH = do_PUT

    return Handler


def serve(port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    dash = Dashboard()
    httpd = ThreadingHTTPServer((HOST, port), make_handler(dash, port))
    url = f"http://{HOST}:{port}/"
    print(f"India Stock Analyzer dashboard: {url}  (Ctrl+C to stop)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
