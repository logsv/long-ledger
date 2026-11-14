import unittest
from datetime import date

from fixtures import cfg, db
from isa.importers.broker import import_holdings, import_trades
from isa.importers.market import import_prices, import_securities
from isa.portfolio import portfolio_view
from isa.tax import build_lots, first_long_term_date, tax_view


def trade(sym, side, qty, price, d, tid):
    return {"symbol": sym, "trade_type": side, "quantity": qty, "price": price, "trade_date": d, "trade_id": tid}


class TaxTest(unittest.TestCase):
    def setUp(self):
        self.cfg = cfg()

    def test_long_term_boundary(self):
        self.assertEqual(first_long_term_date(date(2025, 1, 15), 12), date(2026, 1, 16))
        self.assertEqual(first_long_term_date(date(2024, 2, 29), 12), date(2025, 3, 1))

    def test_fifo_and_terms(self):
        conn = db()
        import_trades(conn, [
            trade("ABC", "buy", 10, 100, "2025-01-15", "1"),
            trade("ABC", "buy", 10, 120, "2025-06-01", "2"),
            trade("ABC", "sell", 15, 150, "2026-01-15", "3"),  # 10 from lot 1 (STCG: anniversary day), 5 from lot 2
        ], "kite")
        book = build_lots(conn, self.cfg.tax)
        self.assertEqual([(r.quantity, r.term) for r in book.realised], [(10, "STCG"), (5, "STCG")])
        self.assertEqual(len(book.open_lots), 1)
        self.assertEqual((book.open_lots[0].quantity, book.open_lots[0].cost), (5, 120))

        conn2 = db()
        import_trades(conn2, [trade("ABC", "buy", 10, 100, "2025-01-15", "1"),
                              trade("ABC", "sell", 10, 150, "2026-01-16", "2")], "kite")
        self.assertEqual(build_lots(conn2, self.cfg.tax).realised[0].term, "LTCG")

    def test_fifo_is_per_account(self):
        conn = db()
        import_trades(conn, [trade("ABC", "buy", 10, 100, "2024-01-01", "1")], "kite")
        import_trades(conn, [trade("ABC", "buy", 10, 200, "2026-01-01", "2"),
                             trade("ABC", "sell", 10, 210, "2026-02-01", "3")], "fivepaisa")
        book = build_lots(conn, self.cfg.tax)
        self.assertEqual(book.realised[0].cost, 200)  # matched in its own demat, not the older kite lot

    def test_unmatched_sell_reported(self):
        conn = db()
        import_trades(conn, [trade("ABC", "sell", 5, 100, "2026-01-01", "1")], "kite")
        self.assertEqual(len(build_lots(conn, self.cfg.tax).errors), 1)

    def test_view_wait_and_exemption(self):
        conn = db()
        import_trades(conn, [
            trade("OLD", "buy", 100, 100, "2024-01-01", "1"),
            trade("OLD", "sell", 50, 1100, "2026-05-01", "2"),   # LTCG 50,000 realised this FY
            trade("NEW", "buy", 100, 100, "2025-12-01", "3"),    # turns long-term 2026-12-02
        ], "kite")
        book = build_lots(conn, self.cfg.tax)
        view = tax_view(book, {"OLD": 1200.0, "NEW": 300.0}, date(2026, 11, 14), self.cfg.tax, 30)
        self.assertEqual(view["ltcg_realised_this_fy"], 50000.0)
        self.assertEqual(view["ltcg_exemption_remaining"], 75000.0)
        new = next(l for l in view["lots"] if l["symbol"] == "NEW")
        self.assertEqual(new["term_if_sold_today"], "STCG")
        self.assertEqual(new["wait_until"], "2026-12-02")
        self.assertEqual(new["est_tax_if_sold"], 20000 * 0.20)
        old = next(l for l in view["lots"] if l["symbol"] == "OLD")
        self.assertEqual(old["est_tax_if_sold"], round((55000 - 75000 if 55000 > 75000 else 0) * 0.125, 2))


class PortfolioTest(unittest.TestCase):
    def test_caps_and_reconciliation(self):
        c = cfg()
        conn = db()
        import_securities(conn, [{"symbol": "AAA", "sector": "Banks"}, {"symbol": "BBB", "sector": "Banks"},
                                 {"symbol": "CCC", "sector": "IT"}])
        import_holdings(conn, [{"symbol": "AAA", "quantity": 100, "average_price": 100},
                               {"symbol": "BBB", "quantity": 10, "average_price": 100},
                               {"symbol": "CCC", "quantity": 10, "average_price": 100}], "kite", as_of="2026-11-14")
        for s, px in (("AAA", 100), ("BBB", 100), ("CCC", 100)):
            import_prices(conn, [{"date": "2026-11-13", "close": px}], symbol=s, source="t")
        import_trades(conn, [trade("AAA", "buy", 90, 100, "2025-01-01", "1")], "kite")
        view = portfolio_view(conn, build_lots(conn, c.tax), c.thresholds)
        names = {(b["type"], b["name"]) for b in view["breaches"]}
        self.assertIn(("stock", "AAA"), names)
        self.assertIn(("sector", "Banks"), names)
        rec = {(r["symbol"]) for r in view["reconciliation"]}
        self.assertIn("AAA", rec)  # 100 at broker vs 90 in lots
        self.assertIn("BBB", rec)  # no trades at all for BBB


if __name__ == "__main__":
    unittest.main()
