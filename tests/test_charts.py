import unittest
from datetime import date

from fixtures import annual_facts, cfg, db, prices
from isa import charts, service
from isa.importers.broker import import_holdings, import_trades
from isa.importers.facts import import_facts
from isa.importers.market import import_prices
from isa.report import render

AS_OF = date(2026, 11, 14)


class ChartsTest(unittest.TestCase):
    def setUp(self):
        self.conn = db()
        import_facts(self.conn, annual_facts("GOODCO", 1000, 0.18, 0.2, 0.01), "test")
        import_prices(self.conn, prices("GOODCO", 200.0, 0.0005), "GOODCO", "test")
        import_prices(self.conn, prices(charts.BENCHMARK, 20000.0, 0.0003), charts.BENCHMARK, "test")
        self.conn.execute("UPDATE security SET is_index = 1 WHERE symbol = ?", (charts.BENCHMARK,))
        import_holdings(self.conn, [{"tradingsymbol": "GOODCO", "quantity": 10, "average_price": 150,
                                     "last_price": 210}], "kite", as_of="2026-11-14")
        import_trades(self.conn, [{"tradingsymbol": "GOODCO", "transaction_type": "BUY", "quantity": 10,
                                   "average_price": 150, "fill_timestamp": "2024-11-14 10:00:00",
                                   "trade_id": "1", "product": "CNC"}], "kite")
        self.conn.commit()
        self.run_ = service.run(self.conn, cfg(), AS_OF, record=False)

    def test_growth_matches_portfolio_and_uses_same_cash_flows_for_index(self):
        g = charts.growth_data(self.conn, self.run_, AS_OF)
        self.assertEqual(g["invested"][-1], 1500)            # broker cost
        self.assertAlmostEqual(g["value"][-1], self.run_["portfolio"]["total_value"], delta=1)
        self.assertEqual(g["index"][0], g["invested"][0])    # index line starts at the money put in
        self.assertIsNotNone(g["xirr_you"])

    def test_portfolio_charts_are_static_escaped_svg(self):
        out = charts.portfolio_charts(self.conn, self.run_, cfg().thresholds, AS_OF)
        self.assertEqual(set(out), {"growth", "allocation", "returns", "tax", "tax_age", "tax_unlock", "tax_gains"})
        for html in out.values():
            self.assertNotIn("<script", html)
            self.assertIn("viz-fig", html)
        self.assertIn("Show data", out["growth"])
        self.assertIn("<title>", out["growth"])               # native hover tooltips

    def test_stock_charts_and_empty_states(self):
        out = charts.stock_charts(self.conn, "GOODCO", AS_OF)
        self.assertIn("<svg", out["price"])
        self.assertIn("Bought 10", out["price"])             # buy marker from the trade
        self.assertIn("<svg", out["business"])
        empty = charts.stock_charts(self.conn, "NOPE", AS_OF)
        self.assertIn("Needs daily prices", empty["price"])
        self.assertIn("/research", empty["business"])

    def test_report_includes_charts_without_scripts(self):
        html = render(self.run_, charts.portfolio_charts(self.conn, self.run_, cfg().thresholds, AS_OF))
        self.assertIn("<h2>Charts</h2>", html)
        self.assertNotIn("<script", html)

    def test_inr_formatting(self):
        self.assertEqual(charts.inr(6081232), "₹60.8L")
        self.assertEqual(charts.inr(12500000), "₹1.25Cr")
        self.assertEqual(charts.inr(-4300), "−₹4.3K")


if __name__ == "__main__":
    unittest.main()
