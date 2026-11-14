"""5paisa Xstream API client: READ-ONLY.

Only the endpoints in READ_ENDPOINTS can be called; any other path is refused
before a request is built. There is no order code in this module, and
tools/security_guards.py fails the build if order-endpoint names appear.

Docs (checked 2026-11-15): https://xstream.5paisa.com/dev-docs
- OAuth login page returns RequestToken (valid 60 min) to ResponseURL.
- GetAccessToken exchanges it; the access token "expires every day at 11:59 PM".
- V3/Holding, V1/TradeBook (today's trades only), V3/NetPositionNetWise.
- V2/historical/{Exch}/{ExchType}/{ScripCode}/{Interval}?from=&end= (daily: no size limit).

Credentials:
- FIVEPAISA_USER_KEY, FIVEPAISA_USER_ID, FIVEPAISA_CLIENT_CODE: non-secret, from the environment or .env.
- Encryption key: macOS Keychain item 'fivepaisa_encryption_key' (set it yourself, see SECURITY.md).
- Access token: stored by this module in the Keychain item 'fivepaisa_access_token'.
"""

from __future__ import annotations

import http.server
import json
import os
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable

IST = timezone(timedelta(hours=5, minutes=30))
API_BASE = "https://Openapi.5paisa.com/VendorsAPI/Service1.svc/"
HIST_BASE = "https://openapi.5paisa.com/V2/historical/"
LOGIN_URL = "https://dev-openapi.5paisa.com/WebVendorLogin/VLogin/Index"

# name -> path under API_BASE. Read-only endpoints ONLY.
READ_ENDPOINTS = {
    "access_token": "GetAccessToken",
    "holdings": "V3/Holding",
    "trade_book": "V1/TradeBook",
    "net_positions": "V3/NetPositionNetWise",
}

ENCRYPTION_KEY_ITEM = "fivepaisa_encryption_key"
TOKEN_ITEM = "fivepaisa_access_token"
DEFAULT_RESPONSE_URL = "http://127.0.0.1:8765/5paisa/callback"


class FivePaisaError(RuntimeError):
    pass


class SessionExpired(FivePaisaError):
    pass


# transport(method, url, headers, body_bytes) -> (status, response_bytes)
Transport = Callable[[str, str, dict, bytes | None], tuple[int, bytes]]


def urllib_transport(method: str, url: str, headers: dict, body: bytes | None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (fixed https hosts)
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


@dataclass(frozen=True)
class Settings:
    user_key: str
    user_id: str
    client_code: str
    response_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        missing = [k for k in ("FIVEPAISA_USER_KEY", "FIVEPAISA_USER_ID", "FIVEPAISA_CLIENT_CODE")
                   if not os.environ.get(k)]
        if missing:
            raise FivePaisaError("set " + ", ".join(missing) + " in .env (see .env.example)")
        return cls(os.environ["FIVEPAISA_USER_KEY"], os.environ["FIVEPAISA_USER_ID"],
                   os.environ["FIVEPAISA_CLIENT_CODE"],
                   os.environ.get("FIVEPAISA_RESPONSE_URL") or DEFAULT_RESPONSE_URL)


def end_of_day_ist(now: datetime | None = None) -> datetime:
    now = (now or datetime.now(IST)).astimezone(IST)
    return now.replace(hour=23, minute=59, second=0, microsecond=0)


class FivePaisaClient:
    def __init__(self, settings: Settings, store, transport: Transport = urllib_transport,
                 clock: Callable[[], datetime] = lambda: datetime.now(IST)):
        self.s = settings
        self.store = store
        self.transport = transport
        self.clock = clock

    # ---- auth --------------------------------------------------------------
    def login_url(self, state: str) -> str:
        q = urllib.parse.urlencode({"VendorKey": self.s.user_key, "ResponseURL": self.s.response_url,
                                    "State": state})
        return f"{LOGIN_URL}?{q}"

    def exchange_request_token(self, request_token: str) -> dict:
        enc = self.store.get(ENCRYPTION_KEY_ITEM)
        if not enc:
            raise FivePaisaError(f"Keychain item '{ENCRYPTION_KEY_ITEM}' is missing (see SECURITY.md)")
        body = self._post("access_token", {"head": {"Key": self.s.user_key},
                                           "body": {"RequestToken": request_token, "EncryKey": enc,
                                                    "UserId": self.s.user_id}}, auth=False)
        token = body.get("AccessToken")
        if not token:
            raise FivePaisaError(f"login failed: {body.get('Message') or 'no access token returned'}")
        expires = end_of_day_ist(self.clock())
        self.store.set(TOKEN_ITEM, json.dumps({"token": token, "client_code": body.get("ClientCode"),
                                               "expires": expires.isoformat()}))
        return {"client_code": body.get("ClientCode"), "client_name": body.get("ClientName"),
                "expires": expires.isoformat()}

    def token_status(self) -> dict:
        raw = self.store.get(TOKEN_ITEM)
        if not raw:
            return {"logged_in": False}
        try:
            t = json.loads(raw)
            expires = datetime.fromisoformat(t["expires"])
        except (ValueError, KeyError):
            return {"logged_in": False, "note": "stored token unreadable"}
        return {"logged_in": self.clock() < expires, "expires": t["expires"],
                "client_code": t.get("client_code")}

    def logout(self) -> bool:
        return self.store.delete(TOKEN_ITEM)

    def _token(self) -> str:
        raw = self.store.get(TOKEN_ITEM)
        if not raw:
            raise SessionExpired("not logged in: run `python3 tools/isa.py fivepaisa login`")
        t = json.loads(raw)
        if self.clock() >= datetime.fromisoformat(t["expires"]):
            raise SessionExpired("5paisa session expired (daily at 23:59 IST): log in again")
        return t["token"]

    # ---- transport ---------------------------------------------------------
    def _post(self, name: str, payload: dict, auth: bool = True) -> dict:
        if name not in READ_ENDPOINTS:
            raise FivePaisaError(f"endpoint {name!r} is not on the read-only allowlist")
        url = API_BASE + READ_ENDPOINTS[name]
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = f"bearer {self._token()}"
        status, raw = self.transport("POST", url, headers, json.dumps(payload).encode())
        return self._unwrap(status, raw)

    @staticmethod
    def _unwrap(status: int, raw: bytes) -> dict:
        if status in (401, 403):
            raise SessionExpired("5paisa rejected the session: log in again")
        if status >= 400:
            raise FivePaisaError(f"5paisa HTTP {status}")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FivePaisaError("5paisa returned non-JSON") from exc
        body = data.get("body") if isinstance(data, dict) else None
        if not isinstance(body, dict):
            raise FivePaisaError("5paisa response has no body")
        st = body.get("Status")
        if st == 9:
            raise SessionExpired("5paisa says the session is invalid: log in again")
        if st not in (0, 1, None):
            raise FivePaisaError(f"5paisa error: {body.get('Message') or st}")
        return body

    # ---- read endpoints ----------------------------------------------------
    def _client_body(self) -> dict:
        return {"head": {"key": self.s.user_key}, "body": {"ClientCode": self.s.client_code}}

    def holdings(self) -> list[dict]:
        return self._post("holdings", self._client_body()).get("Data") or []

    def trade_book(self) -> list[dict]:
        return self._post("trade_book", self._client_body()).get("TradeBookDetail") or []

    def net_positions(self) -> list[dict]:
        return self._post("net_positions", self._client_body()).get("NetPositionDetail") or []

    def daily_candles(self, exch: str, exch_type: str, scrip_code: int, start: date, end: date) -> list[list]:
        if exch not in ("N", "B") or exch_type not in ("C",) or int(scrip_code) <= 0:
            raise FivePaisaError("only NSE/BSE cash-segment daily candles are fetched")
        url = (f"{HIST_BASE}{exch}/{exch_type}/{int(scrip_code)}/1d?"
               + urllib.parse.urlencode({"from": start.isoformat(), "end": end.isoformat()}))
        headers = {"Content-Type": "application/json", "Authorization": f"bearer {self._token()}"}
        status, raw = self.transport("GET", url, headers, None)
        if status == 405:  # docs list the method as POST but show a GET example
            status, raw = self.transport("POST", url, headers, b"")
        if status in (401, 403):
            raise SessionExpired("5paisa rejected the session: log in again")
        if status >= 400:
            raise FivePaisaError(f"5paisa historical HTTP {status}")
        data = json.loads(raw.decode("utf-8"))
        candles = ((data.get("data") or {}).get("candles")) if isinstance(data, dict) else None
        if candles is None:
            raise FivePaisaError("5paisa historical: no candles in response")
        return candles


# ---- browser login with a one-shot localhost callback ------------------------

def wait_for_request_token(response_url: str, state: str, timeout: int = 300,
                           ready: threading.Event | None = None) -> str:
    """Listen once on the 127.0.0.1 ResponseURL and return the RequestToken."""
    u = urllib.parse.urlparse(response_url)
    if u.scheme != "http" or u.hostname not in ("127.0.0.1", "localhost") or not u.port:
        raise FivePaisaError("automatic login needs FIVEPAISA_RESPONSE_URL like http://127.0.0.1:8765/5paisa/callback")
    result: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            p = urllib.parse.urlparse(self.path)
            q = {k.lower(): v[0] for k, v in urllib.parse.parse_qs(p.query).items()}
            ok = p.path == (u.path or "/") and q.get("state") == state and q.get("requesttoken")
            if ok:
                result["token"] = q["requesttoken"]
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(("5paisa login received. You can close this tab." if ok
                              else "Unexpected request: login not completed.").encode())

        def log_message(self, *args):  # keep tokens out of logs
            pass

    server = http.server.HTTPServer(("127.0.0.1", u.port), Handler)
    server.timeout = 1
    if ready:
        ready.set()
    deadline = datetime.now() + timedelta(seconds=timeout)
    try:
        while "token" not in result and datetime.now() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if "token" not in result:
        raise FivePaisaError("timed out waiting for the 5paisa login redirect")
    return result["token"]


def browser_login(client: FivePaisaClient, open_browser: bool = True, timeout: int = 300) -> dict:
    state = secrets.token_urlsafe(16)
    url = client.login_url(state)
    if open_browser:
        webbrowser.open(url)
    token = wait_for_request_token(client.s.response_url, state, timeout)
    return client.exchange_request_token(token)


# ---- sync into the database --------------------------------------------------

def sync(conn, client: FivePaisaClient, today: date | None = None, prices: bool = True,
         history_days: int = 730) -> dict:
    """Holdings snapshot, today's trades and daily prices for held stocks."""
    from ..importers.broker import import_holdings, import_trades
    from ..importers.market import import_prices
    from ..storage.db import normalize_symbol

    today = today or datetime.now(IST).date()
    holdings = client.holdings()
    h = import_holdings(conn, holdings, "fivepaisa", as_of=today.isoformat(), file_name="5paisa-api")
    trades = client.trade_book()
    t = import_trades(conn, trades, "fivepaisa", file_name="5paisa-api")
    out = {"holdings": h["stored"], "holdings_skipped": h["skipped"], "trades": t["stored"],
           "trade_duplicates": t["duplicates"], "trades_skipped": t["skipped"], "prices": {}}
    if prices:
        for row in holdings:
            try:
                symbol = normalize_symbol(str(row.get("Symbol") or ""))
            except ValueError:
                continue
            nse, bse = int(row.get("NseCode") or 0), int(row.get("BseCode") or 0)
            exch, code = ("N", nse) if nse > 0 else ("B", bse)
            if code <= 0:
                out["prices"][symbol] = "no scrip code"
                continue
            last = conn.execute("SELECT MAX(date) FROM price_daily WHERE symbol = ?", (symbol,)).fetchone()[0]
            start = (date.fromisoformat(last) + timedelta(days=1)) if last else today - timedelta(days=history_days)
            if start > today:
                out["prices"][symbol] = 0
                continue
            try:
                candles = client.daily_candles(exch, "C", code, start, today)
            except SessionExpired:
                raise
            except FivePaisaError as exc:
                out["prices"][symbol] = f"error: {exc}"
                continue
            res = import_prices(conn, candles, symbol=symbol, source="fivepaisa", file_name="5paisa-api")
            out["prices"][symbol] = res["stored"]
    return out
