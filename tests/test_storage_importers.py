import json
import sqlite3
import unittest

from fixtures import db  # noqa: F401  (sets sys.path)
from isa import audit
from isa.importers.broker import import_holdings, import_trades
from isa.importers.common import load_records, parse_date
from isa.importers.facts import confirm_facts, import_facts, pending_facts


class AuditTest(unittest.TestCase):
    def test_chain_and_append_only(self):
        conn = db()
        audit.append(conn, "decision", {"action": "held"}, symbol="ABC")
        audit.append(conn, "watchlist", {"action": "add"}, symbol="XYZ")
        self.assertEqual(audit.verify(conn), (True, None))
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("UPDATE audit_event SET payload_json = '{}' WHERE id = 1")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM audit_event")

    def test_unknown_event_rejected(self):
        with self.assertRaises(ValueError):
            audit.append(db(), "place_order", {})


class ParseTest(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(parse_date("2026-11-13 10:15:02"), "2026-11-13")
        self.assertEqual(parse_date("13-11-2026"), "2026-11-13")
        self.assertEqual(parse_date("/Date(1763013600000+0530)/"), "2025-11-13")

    def test_wrapped_json(self):
        rows = load_records(json.dumps({"status": "success", "data": [{"a": 1}]}))
        self.assertEqual(rows, [{"a": 1}])


class BrokerImportTest(unittest.TestCase):
    def test_kite_holdings_include_t1(self):
        conn = db()
        rows = [{"tradingsymbol": "INFY", "isin": "INE009A01021", "exchange": "NSE", "quantity": 10,
                 "t1_quantity": 2, "average_price": 1500.5, "last_price": 1600}]
        res = import_holdings(conn, rows, "kite", as_of="2026-11-14")
        self.assertEqual(res["stored"], 1)
        q = conn.execute("SELECT quantity FROM holding_snapshot").fetchone()[0]
        self.assertEqual(q, 12)

    def test_trades_dedup_and_skip_intraday(self):
        conn = db()
        csv_text = ("symbol,isin,trade_date,exchange,segment,series,trade_type,quantity,price,trade_id\n"
                    "TCS,INE467B01029,2025-01-10,NSE,EQ,EQ,buy,5,3900,T1\n"
                    "TCS,INE467B01029,2025-01-10,NSE,EQ,EQ,buy,5,3900,T1\n")
        res = import_trades(conn, load_records(csv_text), "kite")
        self.assertEqual((res["stored"], res["duplicates"]), (1, 1))
        mis = [{"tradingsymbol": "TCS", "transaction_type": "BUY", "product": "MIS", "quantity": 1,
                "average_price": 1, "fill_timestamp": "2026-11-13 10:00:00", "trade_id": "X"}]
        self.assertEqual(import_trades(conn, mis, "kite")["stored"], 0)

    def test_synthetic_trade_ids_are_stable(self):
        conn = db()
        rows = [{"ScripName": "ITC", "BuySell": "B", "Qty": 10, "Rate": 400,
                 "ExchangeTradeTime": "/Date(1763013600000+0530)/", "DelvIntra": "D"}] * 2
        self.assertEqual(import_trades(conn, rows, "fivepaisa")["stored"], 2)
        again = import_trades(conn, rows, "fivepaisa")
        self.assertEqual((again["stored"], again["duplicates"]), (0, 2))


class FactImportTest(unittest.TestCase):
    def test_validation(self):
        conn = db()
        rows = [{"symbol": "ABC", "metric": "revnue", "period_end": "2026-03-31",
                 "published_at": "2026-05-01", "value": 1}]
        self.assertEqual(import_facts(conn, rows, "x")["stored"], 0)
        rows[0]["metric"] = "revenue"
        rows[0]["published_at"] = "2026-01-01"
        self.assertEqual(import_facts(conn, rows, "x")["stored"], 0)  # published before period end

    def test_llm_facts_pending_until_confirmed(self):
        conn = db()
        row = {"symbol": "ABC", "metric": "revenue", "period_end": "2026-03-31",
               "published_at": "2026-05-01", "value": 100}
        self.assertEqual(import_facts(conn, [row], "ar", extracted_by="llm")["stored"], 0)  # no source_ref
        row["source_ref"] = "ar.pdf p.12"
        res = import_facts(conn, [row], "ar", extracted_by="llm")
        self.assertEqual(res["pending_confirmation"], 1)
        pending = pending_facts(conn)
        self.assertEqual(len(pending), 1)
        self.assertEqual(confirm_facts(conn, [pending[0]["id"]]), 1)
        self.assertEqual(pending_facts(conn), [])


if __name__ == "__main__":
    unittest.main()


class ColumnNameTest(unittest.TestCase):
    def test_pick_ignores_case_spaces_underscores(self):
        from isa.importers.common import pick
        row = {"Trade ID": "1", "Trade Type": "buy"}
        self.assertEqual(pick(row, ("trade_id",)), "1")
        self.assertEqual(pick(row, ("trade_type",)), "buy")
        self.assertIsNone(pick(row, ("order_id",)))
