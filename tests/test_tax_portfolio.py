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
        import_trades(conn, [trade("AAA", "buy", 90, 100, "2025-01-01", "1"),
                             trade("CCC", "buy", 20, 100, "2025-01-01", "2")], "kite")
        book = build_lots(conn, c.tax)
        view = portfolio_view(conn, book, c.thresholds)
        names = {(b["type"], b["name"]) for b in view["breaches"]}
        self.assertIn(("stock", "AAA"), names)
        self.assertIn(("sector", "Banks"), names)
        rec = view["reconciliation"]
        # broker 100 vs 90 traded: 10 opening shares estimated; BBB fully estimated
        self.assertTrue(any(r["symbol"] is None and "estimated" in r["hint"] for r in rec))
        est = {(l.symbol, l.quantity) for l in book.open_lots if l.estimated}
        self.assertEqual(est, {("AAA", 10), ("BBB", 10)})
        # more traded than held (a sell is missing): still a per-stock issue
        self.assertIn("CCC", {r["symbol"] for r in rec})

    def test_opening_lot_terms(self):
        c = cfg()
        conn = db()
        import_holdings(conn, [{"symbol": "OLD", "quantity": 15, "average_price": 50}], "kite", as_of="2026-11-14")
        import_trades(conn, [trade("OLD", "buy", 5, 80, "2026-04-06", "1")], "kite")
        book = build_lots(conn, c.tax)
        opening = [l for l in book.open_lots if l.estimated][0]
        self.assertEqual((opening.quantity, opening.acquired_before), (10, "2026-04-06"))
        view = tax_view(book, {"OLD": 100.0}, date(2026, 11, 14), c.tax, 30)
        lot = next(l for l in view["lots"] if l["estimated"])
        self.assertEqual(lot["term_if_sold_today"], "unknown")   # bought before Apr 2026: may still be short-term
        view2 = tax_view(book, {"OLD": 100.0}, date(2027, 4, 7), c.tax, 30)
        lot2 = next(l for l in view2["lots"] if l["estimated"])
        self.assertEqual(lot2["term_if_sold_today"], "LTCG")     # >12 months after the latest possible buy date


if __name__ == "__main__":
    unittest.main()
