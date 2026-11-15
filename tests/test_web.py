"""Local dashboard server: data endpoints, security checks, actions. Synthetic data only."""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from fixtures import cfg, prices
from isa.importers.broker import import_holdings, import_trades
from isa.importers.market import import_prices
from isa.storage.db import connect
from isa.web import server


class WebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        db = Path(cls.tmp.name) / "t.db"
        conn = connect(db)
        import_prices(conn, prices("AAA", 100.0, 0.0005), symbol="AAA", source="t")
        import_holdings(conn, [{"symbol": "AAA", "quantity": 10, "average_price": 90}], "kite", as_of="2026-11-14")
        import_holdings(conn, [{"symbol": "AAA", "quantity": 4, "average_price": 95}], "fivepaisa", as_of="2026-11-14")
        import_trades(conn, [{"symbol": "AAA", "trade_type": "buy", "quantity": 10, "price": 90,
                              "trade_date": "2026-05-01", "trade_id": "1"}], "kite")
        conn.commit()
        conn.close()
        cls.dash = server.Dashboard(db, cfg())
        cls.httpd = ThreadingHTTPServer((server.HOST, 0), None)
        cls.port = cls.httpd.server_address[1]
        cls.httpd.RequestHandlerClass = server.make_handler(cls.dash, cls.port)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def req(self, path, method="GET", headers=None):
        r = urllib.request.Request(self.base + path, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                return resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as e:
            body = e.read()
            e.close()
            return e.code, body, e.headers

    def test_binds_loopback(self):
        self.assertEqual(server.HOST, "127.0.0.1")
        self.assertEqual(self.httpd.server_address[0], "127.0.0.1")

    def test_index_has_token_and_csp(self):
        code, body, headers = self.req("/")
        self.assertEqual(code, 200)
        self.assertIn(self.dash.token.encode(), body)
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Frame-Options"], "DENY")

    def test_views(self):
        code, body, _ = self.req("/api/holdings")
        rows = json.loads(body)
        self.assertEqual(code, 200)
        self.assertEqual(rows[0]["symbol"], "AAA")
        self.assertEqual(rows[0]["brokers"], "Zerodha 10, 5paisa 4")
        self.assertEqual(set(rows[0]["broker_list"]), {"Zerodha", "5paisa"})
        trades = json.loads(self.req("/api/trades")[1])
        self.assertEqual((trades[0]["broker"], trades[0]["origin"]), ("Zerodha", "Tradebook / API"))
        lots = json.loads(self.req("/api/lots")[1])
        self.assertTrue(any(l["origin"].startswith("Estimated") for l in lots))  # 5paisa has no trades
        ov = json.loads(self.req("/api/overview")[1])
        self.assertEqual(ov["holdings"], 1)
        q = json.loads(self.req("/api/quality")[1])
        self.assertEqual(q["unclassified"], ["AAA"])
        self.assertEqual(q["reconciliation"][0]["broker"], "5paisa")
        self.assertEqual(self.req("/api/nope")[0], 404)

    def test_static_and_traversal(self):
        self.assertEqual(self.req("/static/app.js")[0], 200)
        self.assertEqual(self.req("/static/vendor/tabulator/tabulator.min.js")[0], 200)
        self.assertEqual(self.req("/static/../server.py")[0], 404)
        self.assertEqual(self.req("/static/%2e%2e/server.py")[0], 404)

    def test_host_header_checked(self):
        code, _, _ = self.req("/api/holdings", headers={"Host": "evil.example:80"})
        self.assertEqual(code, 421)

    def test_actions_need_token_and_same_origin(self):
        self.assertEqual(self.req("/api/action/refresh", "POST")[0], 403)
        self.assertEqual(self.req("/api/action/refresh", "POST", {"X-ISA-Token": "wrong"})[0], 403)
        bad_origin = {"X-ISA-Token": self.dash.token, "Origin": "https://evil.example"}
        self.assertEqual(self.req("/api/action/refresh", "POST", bad_origin)[0], 403)
        ok = {"X-ISA-Token": self.dash.token, "Origin": self.base}
        code, body, _ = self.req("/api/action/refresh", "POST", ok)
        self.assertEqual(code, 200, body)
        self.assertEqual(self.req("/api/action/place_order", "POST", ok)[0], 404)
        self.assertEqual(self.req("/api/holdings", "DELETE")[0], 405)

    def test_recompute_is_audited(self):
        ok = {"X-ISA-Token": self.dash.token}
        code, body, _ = self.req("/api/action/recompute", "POST", ok)
        self.assertEqual(code, 200, body)
        conn = connect(self.dash.db)
        try:
            n = conn.execute("SELECT COUNT(*) FROM audit_event WHERE event_type = 'ui_action'").fetchone()[0]
        finally:
            conn.close()
        self.assertGreaterEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
