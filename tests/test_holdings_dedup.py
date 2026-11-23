import unittest

from fixtures import cfg, db
from isa.holdings import effective_snapshots, overlaps
from isa.importers.broker import import_holdings
from isa.portfolio import portfolio_view
from isa.tax import build_lots


class IndmoneyDedupTest(unittest.TestCase):
    """INDmoney reports one total per stock across linked brokers: never add it to Kite/5paisa."""

    def setUp(self):
        self.conn = db()
        import_holdings(self.conn, [{"tradingsymbol": "AAA", "quantity": 669, "average_price": 200, "last_price": 180},
                                    {"tradingsymbol": "BBB", "quantity": 10, "average_price": 50, "last_price": 60}],
                        "kite", as_of="2026-11-17")
        import_holdings(self.conn, [{"symbol": "AAA", "quantity": 804, "invested_amount": 160800, "last_price": 180},
                                    {"symbol": "BBB", "quantity": 10, "invested_amount": 500, "last_price": 60},
                                    {"symbol": "CCC", "quantity": 5, "invested_amount": 500, "last_price": 120}],
                        "indmoney", as_of="2026-11-17")
        self.conn.commit()

    def test_only_the_part_beyond_other_brokers_counts(self):
        snaps = {(r["source"], r["symbol"]): r["quantity"] for r in effective_snapshots(self.conn)}
        self.assertEqual(snaps[("indmoney", "AAA")], 135)    # 804 total - 669 at Kite
        self.assertNotIn(("indmoney", "BBB"), snaps)          # all of it is the Kite holding
        self.assertEqual(snaps[("indmoney", "CCC")], 5)      # held only at INDmoney
        self.assertEqual({o["symbol"] for o in overlaps(self.conn)}, {"AAA", "BBB"})

    def test_portfolio_and_lots_are_not_double_counted(self):
        view = portfolio_view(self.conn, build_lots(self.conn, cfg().tax), cfg().thresholds)
        qty = {h["symbol"]: h["quantity"] for h in view["holdings"]}
        self.assertEqual(qty, {"AAA": 804, "BBB": 10, "CCC": 5})
        self.assertAlmostEqual(view["total_value"], 804 * 180 + 10 * 60 + 5 * 120)
        lots = build_lots(self.conn, cfg().tax).open_lots
        self.assertEqual(sum(l.quantity for l in lots if l.symbol == "AAA"), 804)
        self.assertTrue(any("INDmoney shows 804" in (r["hint"] or "") for r in view["reconciliation"]))


if __name__ == "__main__":
    unittest.main()
