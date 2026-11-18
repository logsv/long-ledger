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


    def test_unofficial_facts_never_auto_confirm(self):
        conn = db()
        rows = [{"symbol": "AAA", "metric": "revenue", "period_end": "2026-03-31", "published_at": "2026-05-10",
                 "value": 120.0, "source": "AAA-NEWS-Q4", "source_ref": "https://news.example/aaa q4", "origin": "third_party"},
                {"symbol": "AAA", "metric": "pat", "period_end": "2026-03-31", "published_at": "2026-05-10",
                 "value": 12.0, "source": "AAA-MODEL", "source_ref": "model knowledge, no document", "origin": "model"}]
        self.assertEqual(import_facts(conn, rows, "research", extracted_by="llm")["stored"], 2)
        for src in ("AAA-NEWS-Q4", "AAA-MODEL"):
            res = confirm_source(conn, src)
            self.assertEqual(res["confirmed"], 0)
            self.assertIn("confirmation by id", res["issues"][0]["issue"])
        self.assertEqual({r["origin"] for r in pending_facts(conn)}, {"third_party", "model"})
        bad = import_facts(conn, [{**rows[0], "origin": "rumour"}], "research", extracted_by="llm")
        self.assertEqual(bad["stored"], 0)
        bad = import_facts(conn, [rows[0]], "manual", extracted_by="import")
        self.assertEqual(bad["stored"], 0)

    def test_research_buckets_and_log(self):
        import io, json, os, tempfile
        from contextlib import redirect_stdout
        from datetime import date
        from isa import coverage
        from isa.importers.broker import import_holdings
        from isa.storage.db import connect

        def run(*argv):
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(cli.main(list(argv)), 0)
            return json.loads(buf.getvalue())

        self.assertEqual(coverage.expected_annual_period(date(2026, 9, 30)), "2025-03-31")
        self.assertEqual(coverage.expected_annual_period(date(2026, 10, 1)), "2026-03-31")
        self.assertEqual(coverage.expected_shareholding_quarter(date(2026, 10, 20)), "2026-06-30")
        self.assertEqual(coverage.expected_shareholding_quarter(date(2026, 10, 22)), "2026-09-30")
        with tempfile.TemporaryDirectory() as d:
            os.environ["ISA_DB_PATH"] = d + "/t.db"
            try:
                conn = connect(d + "/t.db")
                import_holdings(conn, [{"symbol": s, "quantity": q, "last_price": 100}
                                       for s, q in (("AAA", 30), ("BBB", 20), ("CCC", 10))], "kite", as_of="2026-11-14")
                rows = [{"symbol": "AAA", "metric": m, "period_end": f"{y}-03-31", "published_at": f"{y}-08-01",
                         "value": 100.0, "unit": "crore", "source": f"AR {y}"}
                        for y in (2023, 2024, 2025) for m in ("revenue",)]
                import_facts(conn, rows, "research", extracted_by="import")
                conn.commit()
                conn.close()
                run("research-log", "BBB", "--outcome", "failed", "--note", "site down")
                s = run("research-targets", "--summary", "--as-of", "2026-11-18")
                self.assertEqual(s["buckets"]["new"]["top"], ["CCC"])
                self.assertEqual(s["buckets"]["incomplete"]["top"], ["BBB"])
                self.assertEqual(s["buckets"]["stale"]["top"], ["AAA"])  # FY2026 report is out
                t = run("research-targets", "--only", "incomplete", "--as-of", "2026-11-18")["targets"]
                self.assertEqual([x["symbol"] for x in t], ["BBB"])
                self.assertIn("site down", t[0]["reasons"][0])
                t = run("research-targets", "--range", "2-3", "--as-of", "2026-11-18")["targets"]
                self.assertEqual([(x["rank"], x["symbol"]) for x in t], [(2, "BBB"), (3, "CCC")])
                t = run("research-targets", "--only", "new", "--only", "stale", "--top", "1", "--as-of", "2026-11-18")
                self.assertEqual([x["symbol"] for x in t["targets"]], ["AAA"])
                self.assertEqual(run("research-log", "bbb", "--list")["runs"][0]["outcome"], "failed")
            finally:
                os.environ.pop("ISA_DB_PATH", None)


if __name__ == "__main__":
    unittest.main()
