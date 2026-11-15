import json
import unittest

from fixtures import AS_OF, cfg, db, prices, seed_good
from isa import service
from isa.engine import scoring
from isa.engine.base import Data
from isa.engine import market
from isa.importers.broker import import_holdings
from isa.importers.classification import import_classification, parse_networth
from isa.importers.market import import_prices, import_securities
from isa.storage.db import MIGRATIONS, SCHEMA, SCHEMA_VERSION, connect


def seed_indices(conn, broad_drift=0.0005, vix_end_high=False):
    import_prices(conn, prices("NIFTY 500", 20000.0, broad_drift), symbol="NIFTY 500", source="t", is_index=True)
    import_prices(conn, prices("NIFTY 50", 22000.0, broad_drift), symbol="NIFTY 50", source="t", is_index=True)
    vix = prices("INDIA VIX", 20.0, -0.0003)
    if vix_end_high:
        vix[-1]["close"] = 30.0
    import_prices(conn, vix, symbol="INDIA VIX", source="t", is_index=True)
    import_prices(conn, prices("NIFTY IT", 30000.0, 0.001), symbol="NIFTY IT", source="t", is_index=True)
    import_prices(conn, prices("NIFTY BANK", 50000.0, -0.0003), symbol="NIFTY BANK", source="t", is_index=True)


class MigrationTest(unittest.TestCase):
    def test_v1_database_upgrades(self):
        import sqlite3
        raw = sqlite3.connect(":memory:")
        raw.executescript(SCHEMA)
        raw.execute("PRAGMA user_version = 1")
        raw.execute("INSERT INTO security(symbol) VALUES ('OLD')")
        from isa.storage import db as dbmod
        raw.row_factory = sqlite3.Row
        dbmod.migrate(raw)
        cols = {r[1] for r in raw.execute("PRAGMA table_info(security)")}
        self.assertTrue({"asset_class", "market_cap_bucket", "is_etf", "ind_key"} <= cols)
        self.assertEqual(raw.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        raw.close()


class ClassificationTest(unittest.TestCase):
    REPLY = {"result": json.dumps({"holdings": [
        {"investment_code": "K1", "investment": "Good Co Ltd", "assetclass_l2": "equity", "market_cap": "small"},
        {"investment_code": "K2", "investment": "Zerodha Gold ETF", "assetclass_l2": "gold", "market_cap": "small"},
        {"investment_code": "K3", "investment": "Nippon India ETF Nifty 50 BeES", "assetclass_l2": "equity",
         "market_cap": "small"},
        {"investment_code": "K4", "investment": "Unknown Holdings Ltd", "assetclass_l2": "equity", "market_cap": "mid"},
    ]})}

    def test_match_by_name_and_mapping(self):
        conn = db()
        import_securities(conn, [{"symbol": "GOODCO", "name": "GOOD CO LIMITED"},
                                 {"symbol": "GOLDCASE", "isin": "INF0R8F01042"}, {"symbol": "NIFTYBEES"}])
        rows = parse_networth(json.dumps(self.REPLY))
        res = import_classification(conn, rows, mapping=[{"ind_key": "K2", "isin": "INF0R8F01042"},
                                                         {"ind_key": "K3", "symbol": "NIFTYBEES"}])
        self.assertEqual(res["classified"], 3)
        self.assertEqual([u["ind_key"] for u in res["unmatched"]], ["K4"])
        g = dict(conn.execute("SELECT * FROM security WHERE symbol='GOODCO'").fetchone())
        self.assertEqual((g["asset_class"], g["market_cap_bucket"], g["is_etf"], g["ind_key"]),
                         ("equity", "small", 0, "K1"))
        gold = dict(conn.execute("SELECT * FROM security WHERE symbol='GOLDCASE'").fetchone())
        self.assertEqual((gold["asset_class"], gold["is_etf"], gold["market_cap_bucket"]), ("gold", 1, None))
        nb = dict(conn.execute("SELECT * FROM security WHERE symbol='NIFTYBEES'").fetchone())
        self.assertEqual(nb["is_etf"], 1)
        # stored keys are reused without a mapping next time
        again = import_classification(conn, rows)
        self.assertEqual(again["classified"], 3)


class MarketTest(unittest.TestCase):
    def test_regime_from_indices(self):
        conn = db()
        seed_indices(conn, broad_drift=0.0005)
        _, info = market.evaluate(Data(conn, AS_OF), cfg().thresholds, [])
        self.assertEqual(info["regime"], "risk-on")
        self.assertEqual(info["sectors"][0]["index"], "NIFTY IT")
        conn2 = db()
        seed_indices(conn2, broad_drift=-0.0005, vix_end_high=True)
        _, info2 = market.evaluate(Data(conn2, AS_OF), cfg().thresholds, [])
        self.assertEqual(info2["regime"], "risk-off")

    def test_no_index_data_is_unknown(self):
        _, info = market.evaluate(Data(db(), AS_OF), cfg().thresholds, [])
        self.assertTrue(info["regime"].startswith("unknown"))

    def test_market_alone_never_labels(self):
        conn = db()
        seed_indices(conn)
        import_prices(conn, prices("PRICEONLY", 100.0, 0.001), symbol="PRICEONLY", source="t")
        block, _ = market.evaluate(Data(conn, AS_OF), cfg().thresholds, [])
        r = scoring.evaluate(conn, cfg(), "PRICEONLY", AS_OF, market_block=block)
        self.assertEqual(r["label"], "INSUFFICIENT_DATA")

    def test_macro_counts_with_company_data(self):
        conn = db()
        seed_good(conn)
        seed_indices(conn)
        block, _ = market.evaluate(Data(conn, AS_OF), cfg().thresholds, [])
        r = scoring.evaluate(conn, cfg(), "GOODCO", AS_OF, market_block=block)
        self.assertNotIn("macro", r["blocks_not_built"])
        self.assertGreater(r["confidence_parts"]["coverage"], 0.7)


class MonitorAndEtfTest(unittest.TestCase):
    def test_flags_and_etf_label(self):
        c = cfg()
        conn = db()
        seed_indices(conn, broad_drift=0.0008)
        rows = prices("FALLER", 3000.0, -0.0015)
        rows[-1]["volume"] = 1000000
        for r in rows[-20:]:
            r["volume"] = 5000
        import_prices(conn, rows, symbol="FALLER", source="t")
        import_prices(conn, prices("GOLDCASE", 20.0, 0.0004), symbol="GOLDCASE", source="t")
        import_securities(conn, [{"symbol": "FALLER"}, {"symbol": "GOLDCASE"}])
        conn.execute("UPDATE security SET asset_class='gold', is_etf=1 WHERE symbol='GOLDCASE'")
        conn.execute("UPDATE security SET asset_class='equity', market_cap_bucket='small' WHERE symbol='FALLER'")
        import_holdings(conn, [{"symbol": "FALLER", "quantity": 100, "average_price": 400},
                               {"symbol": "GOLDCASE", "quantity": 62, "average_price": 15}], "kite",
                        as_of="2026-11-14")
        run = service.run(conn, c, AS_OF, record=False)
        sig = {s["symbol"]: s for s in run["signals"]}
        self.assertEqual(sig["GOLDCASE"]["label"], "ETF")
        types = {f["type"] for f in sig["FALLER"]["flags"]}
        self.assertTrue({"weak_trend", "deep_drawdown", "loss_from_cost", "volume_spike"} <= types, types)
        self.assertEqual(sig["FALLER"]["label"], "INSUFFICIENT_DATA")  # flags never create a label
        breaches = {(b["type"], b["name"]) for b in run["portfolio"]["breaches"]}
        self.assertIn(("asset_class", "gold + silver"), breaches)
        self.assertIn(("market_cap", "small caps"), breaches)
        from isa.report import render
        html = render(run)
        self.assertIn("Regime:", html)
        self.assertIn("Allocation", html)
        self.assertIn("Monitoring mode", html)          # no company data anywhere
        self.assertNotIn("missing:", html)              # no per-row clutter
        self.assertLess(html.index("FALLER"), html.index("GOLDCASE"))  # flagged stocks first


if __name__ == "__main__":
    unittest.main()


class BrokerColumnTest(unittest.TestCase):
    def test_report_lists_brokers_with_quantities(self):
        conn = db()
        import_prices(conn, [{"date": "2026-11-13", "close": 100}], symbol="AAA", source="t")
        import_holdings(conn, [{"symbol": "AAA", "quantity": 30, "average_price": 90}], "kite", as_of="2026-11-14")
        import_holdings(conn, [{"symbol": "AAA", "quantity": 12, "average_price": 95}], "fivepaisa", as_of="2026-11-14")
        run = service.run(conn, cfg(), AS_OF, record=False)
        h = run["portfolio"]["holdings"][0]
        self.assertEqual(h["by_account"], {"kite": 30, "fivepaisa": 12})
        from isa.report import render
        html = render(run)
        self.assertIn("<th>Brokers</th>", html)
        self.assertIn("Zerodha 30<br>5paisa 12", html)
