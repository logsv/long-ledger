import unittest
from datetime import date

from fixtures import AS_OF, cfg, db, seed_bad, seed_good
from isa.engine import scoring
from isa.importers.facts import import_facts


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.cfg = cfg()
        self.conn = db()
        seed_good(self.conn)
        seed_bad(self.conn)

    def test_good_company_is_positive(self):
        r = scoring.evaluate(self.conn, self.cfg, "GOODCO", AS_OF)
        self.assertIn(r["label"], ("BUY", "ACCUMULATE"), r["why"])
        self.assertGreater(r["confidence"], 30)
        self.assertLessEqual(r["confidence"], 70.0)  # Phase 2 blocks missing caps coverage at 0.7
        self.assertTrue(r["why"]["positive"])
        iv = r["blocks"]["valuation"]["extra"]["intrinsic_value"]
        self.assertLess(iv["low"], iv["base"])
        self.assertLess(iv["base"], iv["high"])

    def test_bad_company_vetoed_and_negative(self):
        r = scoring.evaluate(self.conn, self.cfg, "BADCO", AS_OF)
        self.assertNotIn(r["label"], ("BUY", "ACCUMULATE"))
        self.assertIn(r["label"], ("TRIM", "SELL"))
        self.assertTrue(any("pledge" in v for v in r["veto"]))
        self.assertTrue(any("qualified" in v for v in r["veto"]))

    def test_insufficient_data(self):
        r = scoring.evaluate(self.conn, self.cfg, "UNKNOWN", AS_OF)
        self.assertEqual(r["label"], "INSUFFICIENT_DATA")
        self.assertEqual(r["confidence"], 0.0)

    def test_deterministic(self):
        a = scoring.evaluate(self.conn, self.cfg, "GOODCO", AS_OF)
        b = scoring.evaluate(self.conn, self.cfg, "GOODCO", AS_OF)
        self.assertEqual(a["inputs_hash"], b["inputs_hash"])
        self.assertEqual(a["label"], b["label"])

    def test_point_in_time(self):
        # A fact published after as_of must not be used.
        before = scoring.evaluate(self.conn, self.cfg, "GOODCO", date(2026, 5, 1))
        fy26_rev = [e for e in before["blocks"]["fundamentals"]["evidence"] if e["key"].startswith("revenue_cagr")]
        self.assertEqual(fy26_rev[0]["as_of"], "2025-03-31")

    def test_unconfirmed_llm_fact_ignored(self):
        import_facts(self.conn, [{"symbol": "GOODCO", "metric": "auditor_qualified", "period_end": "2026-03-31",
                                  "published_at": "2026-05-21", "value": 1, "source_ref": "ar.pdf p.80"}],
                     source="ar-llm", extracted_by="llm")
        r = scoring.evaluate(self.conn, self.cfg, "GOODCO", AS_OF)
        self.assertFalse(r["veto"])

    def test_thesis_broken_forces_sell(self):
        self.conn.execute("INSERT INTO thesis_condition(symbol, metric, op, threshold, note, created_at)"
                          " VALUES ('GOODCO', 'debt_to_equity', '>=', 5, 'test', '2026-01-01')")
        r = scoring.evaluate(self.conn, self.cfg, "GOODCO", AS_OF, position={"unrealised_pct": 0.1})
        self.assertEqual(r["label"], "SELL")
        self.assertEqual(r["triggers"][0]["type"], "thesis_broken")

    def test_loss_alone_does_not_sell(self):
        r = scoring.evaluate(self.conn, self.cfg, "GOODCO", AS_OF, position={"unrealised_pct": -0.35})
        self.assertIn(r["label"], ("BUY", "ACCUMULATE"))
        self.assertIn("loss_watch", [t["type"] for t in r["triggers"]])

    def test_technicals_never_change_label(self):
        r = scoring.evaluate(self.conn, self.cfg, "GOODCO", AS_OF)
        self.assertNotIn("technicals", r["blocks"])
        self.assertIn("advice", r["technicals"])

    def test_record_audits_signal(self):
        r = scoring.evaluate(self.conn, self.cfg, "GOODCO", AS_OF)
        sid = scoring.record(self.conn, r)
        ev = self.conn.execute("SELECT event_type, payload_json FROM audit_event").fetchall()
        self.assertEqual(ev[-1][0], "signal")
        self.assertIn(str(sid), ev[-1][1])


if __name__ == "__main__":
    unittest.main()
