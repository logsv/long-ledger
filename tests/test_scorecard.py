import unittest
from datetime import date

from fixtures import annual_facts, cfg, db, prices
from isa import scorecard, service
from isa.importers.broker import import_holdings, import_trades
from isa.importers.facts import import_facts
from isa.importers.market import import_prices


class ScorecardTest(unittest.TestCase):
    def setUp(self):
        self.conn = db()
        import_facts(self.conn, annual_facts("GOODCO", 1000, 0.18, 0.2, 0.01), "test")
        import_prices(self.conn, prices("GOODCO", 200.0, 0.0), "GOODCO", "test")
        import_holdings(self.conn, [{"tradingsymbol": "GOODCO", "quantity": 10, "average_price": 150,
                                     "last_price": 210}], "kite", as_of="2026-11-14")
        import_trades(self.conn, [{"tradingsymbol": "GOODCO", "transaction_type": "BUY", "quantity": 10,
                                   "average_price": 150, "fill_timestamp": "2024-11-14 10:00:00",
                                   "trade_id": "1", "product": "CNC"}], "kite")
        self.conn.commit()

    def test_card_has_four_groups_and_uses_broker_price(self):
        run = service.run(self.conn, cfg(), date(2026, 11, 14), record=False)
        card = run["scorecards"]["GOODCO"]
        self.assertEqual([g["title"] for g in card["groups"]],
                         ["Is it cheap?", "Is it a good business?", "Is it growing?", "Is it safe?"])
        self.assertEqual(card["of"], 12)
        self.assertGreaterEqual(card["filled"], 10)
        self.assertEqual(card["price"], 210)  # broker's last price is newer than the last daily close
        m = {x["key"]: x for g in card["groups"] for x in g["metrics"]}
        self.assertIsNotNone(m["pe"]["value"])
        self.assertIn(m["roce"]["tone"], ("good", "ok", "bad", "neutral"))
        self.assertAlmostEqual(card["your_return"]["value"], 18.3, delta=0.2)  # 150 -> 210 over two years

    def test_missing_data_is_shown_not_guessed(self):
        import_holdings(self.conn, [{"tradingsymbol": "EMPTY", "quantity": 1, "average_price": 10,
                                     "last_price": 12}], "kite", as_of="2026-11-14")
        run = service.run(self.conn, cfg(), date(2026, 11, 14), record=False)
        card = run["scorecards"]["EMPTY"]
        self.assertEqual(card["filled"], 0)
        for g in card["groups"]:
            for m in g["metrics"]:
                self.assertIsNone(m["value"])
                self.assertEqual(m["tone"], "missing")
                self.assertIn("/research", m["text"] + "/research")

    def test_xirr_and_short_holdings(self):
        r = scorecard.xirr([(date(2024, 1, 1), -100.0), (date(2025, 1, 1), 110.0)])
        self.assertAlmostEqual(r, 0.10, delta=0.001)
        lots = [{"symbol": "X", "buy_date": "2026-06-01", "quantity": 10, "cost": 100.0}]
        res = scorecard.own_return(lots, "X", 120.0, date(2026, 11, 1))
        self.assertIsNone(res["value"])
        self.assertAlmostEqual(res["simple"], 20.0)
        self.assertIn("not annualised", res["text"])


if __name__ == "__main__":
    unittest.main()
