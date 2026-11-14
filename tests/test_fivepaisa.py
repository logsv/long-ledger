"""5paisa client against a fake transport: no network, no real credentials."""

import json
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime

from fixtures import db
from isa.brokers import fivepaisa as fp
from isa.brokers.keychain import MemoryStore

NOW = datetime(2026, 11, 15, 10, 0, tzinfo=fp.IST)


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.historical_method_ok = "GET"

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, json.loads(body) if body else None))
        path = url.split("?")[0]
        if path.endswith("GetAccessToken"):
            return 200, json.dumps({"head": {"Status": 0}, "body": {
                "AccessToken": "jwt-token", "ClientCode": "C123", "ClientName": "Test", "Status": 0,
                "Message": "Success"}}).encode()
        if path.endswith("V3/Holding"):
            return 200, json.dumps({"head": {}, "body": {"Status": 0, "Data": [
                {"Symbol": "ITC", "FullName": "ITC LTD", "Quantity": 50, "AvgRate": 400.5,
                 "CurrentPrice": 410.0, "NseCode": 1660, "BseCode": 500875, "Exch": "N", "ExchType": "C"},
            ]}}).encode()
        if path.endswith("V1/TradeBook"):
            return 200, json.dumps({"head": {}, "body": {"Status": 0, "TradeBookDetail": [
                {"ScripName": "ITC", "BuySell": "B", "Qty": 10, "Rate": 405, "DelvIntra": "D",
                 "ExchangeTradeID": "E1", "ExchangeTradeTime": "/Date(1763181000000+0530)/", "Exch": "N"},
                {"ScripName": "SBIN", "BuySell": "B", "Qty": 5, "Rate": 800, "DelvIntra": "I",
                 "ExchangeTradeID": "E2", "ExchangeTradeTime": "/Date(1763181000000+0530)/", "Exch": "N"},
            ]}}).encode()
        if "/V2/historical/" in path:
            if method != self.historical_method_ok:
                return 405, b""
            return 200, json.dumps({"status": "success", "data": {"candles": [
                ["2026-11-13T00:00:00", 400, 412, 398, 409.5, 1000],
                ["2026-11-14T00:00:00", 409, 415, 405, 410.0, 1200]]}}).encode()
        return 404, b"{}"


def client(transport=None, store=None):
    s = fp.Settings("UKEY", "UID", "C123", "http://127.0.0.1:8799/5paisa/callback")
    return fp.FivePaisaClient(s, store or MemoryStore({fp.ENCRYPTION_KEY_ITEM: "enc"}),
                              transport or FakeTransport(), clock=lambda: NOW)


class AuthTest(unittest.TestCase):
    def test_login_url(self):
        url = client().login_url("abc")
        self.assertTrue(url.startswith(fp.LOGIN_URL + "?"))
        self.assertIn("VendorKey=UKEY", url)
        self.assertIn("State=abc", url)

    def test_token_exchange_stores_token_not_returned(self):
        t = FakeTransport()
        store = MemoryStore({fp.ENCRYPTION_KEY_ITEM: "enc"})
        res = client(t, store).exchange_request_token("REQ")
        self.assertNotIn("jwt-token", json.dumps(res))
        self.assertEqual(res["expires"], "2026-11-15T23:59:00+05:30")
        self.assertEqual(json.loads(store.get(fp.TOKEN_ITEM))["token"], "jwt-token")
        sent = t.calls[0][3]
        self.assertEqual(sent, {"head": {"Key": "UKEY"},
                                "body": {"RequestToken": "REQ", "EncryKey": "enc", "UserId": "UID"}})
        self.assertNotIn("Authorization", t.calls[0][2])

    def test_missing_encryption_key(self):
        with self.assertRaises(fp.FivePaisaError):
            client(store=MemoryStore()).exchange_request_token("REQ")

    def test_expired_token(self):
        store = MemoryStore({fp.TOKEN_ITEM: json.dumps({"token": "x", "expires": "2026-11-14T23:59:00+05:30"})})
        c = client(store=store)
        self.assertFalse(c.token_status()["logged_in"])
        with self.assertRaises(fp.SessionExpired):
            c.holdings()

    def test_invalid_session_status(self):
        def t(method, url, headers, body):
            return 200, json.dumps({"head": {}, "body": {"Status": 9, "Message": "Invalid Session"}}).encode()
        store = MemoryStore({fp.TOKEN_ITEM: json.dumps({"token": "x", "expires": "2026-11-15T23:59:00+05:30"})})
        with self.assertRaises(fp.SessionExpired):
            client(t, store).holdings()


class ReadOnlyTest(unittest.TestCase):
    def test_allowlist_is_read_only(self):
        self.assertEqual(set(fp.READ_ENDPOINTS.values()),
                         {"GetAccessToken", "V3/Holding", "V1/TradeBook", "V3/NetPositionNetWise"})

    def test_unknown_endpoint_refused_before_any_request(self):
        t = FakeTransport()
        with self.assertRaises(fp.FivePaisaError):
            client(t)._post("orders", {})
        self.assertEqual(t.calls, [])

    def test_candles_only_cash_segment(self):
        with self.assertRaises(fp.FivePaisaError):
            client().daily_candles("N", "D", 123, date(2026, 1, 1), date(2026, 2, 1))


class SyncTest(unittest.TestCase):
    def _logged_in(self, transport):
        store = MemoryStore({fp.TOKEN_ITEM: json.dumps({"token": "jwt", "expires": "2026-11-15T23:59:00+05:30"})})
        return client(transport, store)

    def test_sync_imports_holdings_trades_prices(self):
        conn = db()
        t = FakeTransport()
        res = fp.sync(conn, self._logged_in(t), today=date(2026, 11, 15))
        self.assertEqual(res["holdings"], 1)
        self.assertEqual(res["trades"], 1)  # the intraday SBIN trade is skipped
        self.assertEqual(res["prices"]["ITC"], 2)
        row = conn.execute("SELECT quantity, avg_price FROM holding_snapshot WHERE symbol='ITC'").fetchone()
        self.assertEqual(tuple(row), (50, 400.5))
        hist = [c for c in t.calls if "/V2/historical/N/C/1660/1d" in c[1]]
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0][2]["Authorization"], "bearer jwt")
        self.assertTrue(all(c[1].startswith(("https://Openapi.5paisa.com/", "https://openapi.5paisa.com/"))
                            for c in t.calls))

    def test_historical_falls_back_to_post(self):
        conn = db()
        t = FakeTransport()
        t.historical_method_ok = "POST"
        res = fp.sync(conn, self._logged_in(t), today=date(2026, 11, 15))
        self.assertEqual(res["prices"]["ITC"], 2)

    def test_second_sync_is_incremental(self):
        conn = db()
        c = self._logged_in(FakeTransport())
        fp.sync(conn, c, today=date(2026, 11, 15))
        t2 = FakeTransport()
        c.transport = t2
        fp.sync(conn, c, today=date(2026, 11, 15))
        hist = [x for x in t2.calls if "/V2/historical/" in x[1]]
        self.assertIn("from=2026-11-15", hist[0][1])


class CallbackTest(unittest.TestCase):
    def test_localhost_callback_checks_state(self):
        ready, out = threading.Event(), {}

        def serve():
            out["token"] = fp.wait_for_request_token("http://127.0.0.1:8799/5paisa/callback", "S1", timeout=10,
                                                     ready=ready)

        th = threading.Thread(target=serve)
        th.start()
        ready.wait(5)
        with self.assertRaises(urllib.error.HTTPError) as ctx:  # wrong state is rejected (HTTP 400)
            urllib.request.urlopen("http://127.0.0.1:8799/5paisa/callback?RequestToken=BAD&state=nope", timeout=5)
        ctx.exception.close()
        urllib.request.urlopen("http://127.0.0.1:8799/5paisa/callback?RequestToken=GOOD&state=S1", timeout=5)
        th.join(10)
        self.assertEqual(out["token"], "GOOD")

    def test_non_local_response_url_refused(self):
        with self.assertRaises(fp.FivePaisaError):
            fp.wait_for_request_token("https://example.com/cb", "S", timeout=1)


if __name__ == "__main__":
    unittest.main()
