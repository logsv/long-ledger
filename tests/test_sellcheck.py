import unittest
from datetime import date

from fixtures import annual_facts, cfg, db, prices
from isa import charts, sellcheck, service
from isa.importers.broker import import_holdings, import_trades
from isa.importers.facts import import_facts
from isa.importers.market import import_prices

AS_OF = date(2026, 11, 14)


class SellCheckTest(unittest.TestCase):
    def setUp(self):
        self.conn = db()
        import_facts(self.conn, annual_facts("GOODCO", 1000, 0.18, 0.2, 0.01), "test")
        import_prices(self.conn, prices("GOODCO", 200.0, 0.0005), "GOODCO", "test")
        import_prices(self.conn, prices(charts.BENCHMARK, 20000.0, 0.0003), charts.BENCHMARK, "test")
        import_holdings(self.conn, [{"tradingsymbol": "GOODCO", "quantity": 10, "average_price": 150,
                                     "last_price": 210}], "kite", as_of="2026-11-14")
        import_trades(self.conn, [{"tradingsymbol": "GOODCO", "transaction_type": "BUY", "quantity": 10,
                                   "average_price": 150, "fill_timestamp": "2026-06-01 10:00:00",
                                   "trade_id": "1", "product": "CNC"}], "kite")
        self.conn.commit()
        self.cfg = cfg()
        self.run_ = service.run(self.conn, self.cfg, AS_OF, record=False)
        self.sig = next(s for s in self.run_["signals"] if s["symbol"] == "GOODCO")

    def test_four_checks_with_status_and_tax(self):
        c = sellcheck.check(self.conn, self.cfg, self.sig, AS_OF, self.run_["tax"]["lots"])
        self.assertEqual([x["key"] for x in c["checks"]], ["fundamentals", "trend", "future", "team"])
        for x in c["checks"]:
            self.assertIn(x["status"], ("good", "watch", "bad", "unknown"))
        self.assertEqual(c["checks"][2]["status"], "unknown")          # no thesis written yet
        self.assertIn("/thesis", c["checks"][2]["headline"])
        self.assertEqual(c["tax"]["lots"], 1)
        self.assertIsNotNone(c["tax"]["next_long_term"])               # bought June 2026: still short-term

    def test_broken_thesis_is_a_concern(self):
        self.conn.execute("INSERT INTO thesis_condition(symbol, metric, op, threshold, note, created_at)"
                          " VALUES ('GOODCO', 'roce', '>', 500, 'impossible bar', '2026-01-01')")
        c = sellcheck.check(self.conn, self.cfg, self.sig, AS_OF, self.run_["tax"]["lots"])
        fut = c["checks"][2]
        self.assertEqual(fut["status"], "bad")
        self.assertIn("1 of 1 thesis conditions broken", fut["headline"])

    def test_score_history_is_point_in_time(self):
        hist = sellcheck.score_history(self.conn, "GOODCO", AS_OF, self.cfg.thresholds, quarters=12)
        self.assertEqual(len(hist), 13)
        self.assertEqual(hist[-1]["date"], AS_OF.isoformat())
        self.assertIsNotNone(hist[-1]["fundamentals"])

    def test_html_status_never_colour_alone(self):
        c = sellcheck.check(self.conn, self.cfg, self.sig, AS_OF, self.run_["tax"]["lots"])
        html = charts.sell_check_html(self.conn, c, AS_OF, self.cfg.thresholds)
        self.assertNotIn("<script", html)
        self.assertNotIn("{trig}", html)
        self.assertTrue(any(w in html for w in ("✓ OK", "! Watch", "✗ Concern", "? No data")))
        table = charts.sell_review_table([c])
        self.assertIn("GOODCO", table)

    def test_tax_lot_charts(self):
        out = charts.portfolio_charts(self.conn, self.run_, self.cfg.thresholds, AS_OF)
        self.assertIn("How long you have held", out["tax_age"])
        self.assertIn("Value turning long-term", out["tax_unlock"])
        self.assertIn("Unrealised gains by tax type", out["tax_gains"])


if __name__ == "__main__":
    unittest.main()
