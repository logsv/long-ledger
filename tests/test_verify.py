import unittest

from fixtures import cfg, db
from isa.importers.facts import import_facts, pending_facts
from isa.importers.verify import apply_verifications, site_of, verify_targets

DENIED = {"screener.in", "nseindia.com"}


def pending(conn, metric="revenue", value=1000.0, ref="https://www.care-ratings.com/x.pdf p.2"):
    import_facts(conn, [{"symbol": "ACME", "metric": metric, "period_end": "2026-03-31",
                         "published_at": "2026-05-20", "value": value, "source": "ACME-CARE-FY2026",
                         "source_ref": ref}], "research", extracted_by="llm")
    return pending_facts(conn)[0]["id"]


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.conn = db()
        self.v = cfg().thresholds["verification"]

    def run_one(self, fid, value, url):
        return apply_verifications(self.conn, [{"fact_id": fid, "value": value, "source_url": url}],
                                   self.v, DENIED)["results"][0]

    def test_site_of(self):
        self.assertEqual(site_of("https://investors.srf.com/ar.pdf p.4"), "srf.com")
        self.assertEqual(site_of("see https://www.acme.co.in/x.pdf"), "acme.co.in")
        self.assertIsNone(site_of("annual report p.4"))

    def test_targets_hide_value_and_name_avoid_site(self):
        fid = pending(self.conn)
        t = verify_targets(self.conn)[0]
        self.assertEqual(t["fact_id"], fid)
        self.assertNotIn("value", t)
        self.assertEqual(t["avoid_sites"], ["care-ratings.com"])

    def test_independent_match_confirms(self):
        fid = pending(self.conn)
        r = self.run_one(fid, 1005, "https://ir.acme.com/results.pdf p.3")
        self.assertEqual(r["verdict"], "match")
        self.assertEqual(pending_facts(self.conn), [])
        events = [x[0] for x in self.conn.execute("SELECT event_type FROM audit_event")]
        self.assertIn("fact_verified", events)

    def test_mismatch_stays_pending(self):
        fid = pending(self.conn)
        self.assertEqual(self.run_one(fid, 1100, "https://ir.acme.com/r.pdf")["verdict"], "mismatch")
        self.assertEqual(len(pending_facts(self.conn)), 1)

    def test_same_site_is_not_independent(self):
        fid = pending(self.conn)
        self.assertEqual(self.run_one(fid, 1000, "https://care-ratings.com/other.pdf")["verdict"], "not_independent")
        self.assertEqual(len(pending_facts(self.conn)), 1)

    def test_denied_site_never_confirms(self):
        fid = pending(self.conn)
        self.assertEqual(self.run_one(fid, 1000, "https://www.screener.in/company/ACME/")["verdict"], "denied_source")
        fid2 = pending(self.conn, metric="pat", value=100, ref="https://nseindia.com/x p.1")
        self.assertEqual(self.run_one(fid2, 100, "https://ir.acme.com/r.pdf")["verdict"], "denied_source")
        self.assertEqual(len(pending_facts(self.conn)), 2)

    def test_not_found_and_missing_url(self):
        fid = pending(self.conn)
        self.assertEqual(self.run_one(fid, None, "https://ir.acme.com/r.pdf")["verdict"], "not_found")
        self.assertEqual(self.run_one(fid, 1000, None)["verdict"], "no_source")
        self.assertEqual(len(pending_facts(self.conn)), 1)

    def test_percent_tolerance_in_points(self):
        fid = pending(self.conn, metric="promoter_pct", value=52.3)
        self.assertEqual(self.run_one(fid, 52.6, "https://ir.acme.com/shp.pdf")["verdict"], "mismatch")
        self.assertEqual(self.run_one(fid, 52.35, "https://ir.acme.com/shp.pdf")["verdict"], "match")

    def test_denied_sites_read_local_settings_too(self):
        import json, tempfile
        from pathlib import Path
        from isa.importers.verify import denied_sites
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d, "settings.json"), Path(d, "settings.local.json")
            a.write_text(json.dumps({"permissions": {"deny": ["WebFetch(domain:screener.in)", "Read(.env)"]}}))
            b.write_text(json.dumps({"permissions": {"deny": ["WebFetch(domain:www.pocketful.in)"]}}))
            self.assertEqual(denied_sites([a, b]), {"screener.in", "pocketful.in"})

    def test_tried_sites_are_avoided_next_time(self):
        fid = pending(self.conn)
        self.run_one(fid, None, "https://ir.acme.com/r.pdf")
        self.assertEqual(verify_targets(self.conn)[0]["avoid_sites"], ["acme.com", "care-ratings.com"])


if __name__ == "__main__":
    unittest.main()
