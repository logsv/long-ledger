import unittest

from fixtures import annual_facts, cfg, db
from isa import cli
from isa.importers.facts import check_facts, confirm_source, import_facts, pending_facts


def llm(rows, source):
    for r in rows:
        r["source"] = source
        r["source_ref"] = "https://example-company.in/ar.pdf p.10"
    return rows


class FactChecksTest(unittest.TestCase):
    def test_clean_document_auto_confirms(self):
        conn = db()
        rows = llm([r for r in annual_facts("GOODCO", 1000, 0.18, 0.20, 0.01)
                    if r["period_end"].endswith("03-31") and r["metric"] != "auditor_qualified"], "GOODCO-AR-FY2026")
        import_facts(conn, rows, "research", extracted_by="llm")
        self.assertEqual(check_facts(conn, source="GOODCO-AR-FY2026"), [])
        res = confirm_source(conn, "GOODCO-AR-FY2026")
        self.assertGreater(res["confirmed"], 50)
        self.assertEqual(pending_facts(conn), [])

    def test_unit_error_blocks_confirmation(self):
        conn = db()
        rows = llm([{"symbol": "BAD", "metric": m, "period_end": "2026-03-31", "published_at": "2026-05-20", "value": v}
                    for m, v in (("revenue", 1000), ("pat", 100), ("shares_outstanding", 10), ("eps", 1000),
                                 ("ebit", 200), ("ebitda", 150), ("promoter_pct", 140))], "BAD-AR-FY2026")
        rows += llm([{"symbol": "BAD", "metric": "revenue", "period_end": "2025-03-31", "published_at": "2025-05-20",
                      "value": 100000}], "BAD-AR-FY2026")
        import_facts(conn, rows, "research", extracted_by="llm")
        issues = {i["metric"]: i["issue"] for i in check_facts(conn, source="BAD-AR-FY2026")}
        self.assertIn("eps", issues)            # EPS 1000 vs PAT/shares 10
        self.assertIn("ebit", issues)           # ebit > ebitda
        self.assertIn("promoter_pct", issues)   # 140%
        self.assertIn("revenue", issues)        # 100000 -> 1000 jump
        res = confirm_source(conn, "BAD-AR-FY2026")
        self.assertEqual(res["confirmed"], 0)
        self.assertTrue(res["issues"])
        self.assertEqual(len(pending_facts(conn)), len(rows))

    def test_research_targets_cli(self):
        import io, json, os, tempfile
        from contextlib import redirect_stdout
        from isa.importers.broker import import_holdings
        with tempfile.TemporaryDirectory() as d:
            os.environ["ISA_DB_PATH"] = d + "/t.db"
            try:
                from isa.storage.db import connect
                conn = connect(d + "/t.db")
                import_holdings(conn, [{"symbol": "AAA", "quantity": 10, "last_price": 100},
                                       {"symbol": "BBB", "quantity": 1, "last_price": 100}], "kite", as_of="2026-11-14")
                conn.commit()
                conn.close()
                buf = io.StringIO()
                with redirect_stdout(buf):
                    cli.main(["research-targets", "--top", "5"])
                out = json.loads(buf.getvalue())
                self.assertEqual([t["symbol"] for t in out["targets"]], ["AAA", "BBB"])
                self.assertEqual(out["targets"][0]["needs"], "full history")
            finally:
                os.environ.pop("ISA_DB_PATH", None)


if __name__ == "__main__":
    unittest.main()
