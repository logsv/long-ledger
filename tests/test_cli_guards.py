import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from fixtures import ROOT, annual_facts, prices
from isa import cli


def run(*args) -> dict:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(list(args))
    out = json.loads(buf.getvalue())
    if code != 0:
        raise AssertionError(out)
    return out


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        os.environ["ISA_DB_PATH"] = str(self.dir / "t.db")

    def tearDown(self):
        os.environ.pop("ISA_DB_PATH", None)
        self.tmp.cleanup()

    def write(self, name, obj) -> str:
        p = self.dir / name
        p.write_text(json.dumps(obj))
        return str(p)

    def test_end_to_end(self):
        run("init")
        run("import-holdings", "--source", "kite", "--as-of", "2026-11-14", "--file",
            self.write("h.json", {"data": [{"tradingsymbol": "GOODCO", "quantity": 10, "average_price": 150,
                                            "last_price": 200}]}))
        run("import-trades", "--source", "kite", "--file",
            self.write("t.json", [{"tradingsymbol": "GOODCO", "transaction_type": "BUY", "quantity": 10,
                                   "average_price": 150, "fill_timestamp": "2025-12-01 10:00:00",
                                   "trade_id": "1", "product": "CNC"}]))
        run("import-facts", "--source", "test", "--file", self.write("f.json", annual_facts("GOODCO", 1000, 0.18, 0.2, 0.01)))
        run("import-prices", "--symbol", "GOODCO", "--source", "test", "--file",
            self.write("p.json", prices("GOODCO", 200.0, 0.0)))
        run("security", "GOODCO", "--sector", "Industrials")
        run("watch", "add", "OTHER")
        out = run("portfolio", "--as-of", "2026-11-14")
        labels = {s["symbol"]: s["label"] for s in out["signals"]}
        self.assertEqual(labels["OTHER"], "INSUFFICIENT_DATA")
        self.assertIn(labels["GOODCO"], ("BUY", "ACCUMULATE"))
        self.assertEqual(out["reconciliation"], [])
        rep = run("report", "--as-of", "2026-11-14", "--out", str(self.dir / "r.html"))
        html = Path(rep["report"]).read_text()
        self.assertIn("GOODCO", html)
        self.assertNotIn("<script", html)
        self.assertTrue(run("audit", "verify")["ok"])
        run("decision", "GOODCO", "held", "--note", "reviewed")

    def test_daily_summary(self):
        run("init")
        run("import-holdings", "--source", "kite", "--as-of", "2026-11-14", "--file",
            self.write("h.json", {"data": [{"tradingsymbol": "GOODCO", "quantity": 10, "average_price": 150,
                                            "last_price": 200}]}))
        run("import-prices", "--symbol", "GOODCO", "--source", "test", "--file",
            self.write("p.json", prices("GOODCO", 200.0, 0.001)))
        run("daily", "--as-of", "2026-11-13")  # yesterday's signals
        out = run("daily", "--as-of", "2026-11-14", "--no-record")
        self.assertEqual(out["previous_signals_from"], "2026-11-13")
        self.assertIsNotNone(out["day_change"])
        for key in ("label_changes", "new_flags", "new_triggers", "breaches", "turning_long_term_30d", "research"):
            self.assertIn(key, out)

    def test_bad_input_returns_error(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["import-holdings", "--source", "kite", "--file", str(self.dir / "missing.json")])
        self.assertEqual(code, 2)
        self.assertIn("error", json.loads(buf.getvalue()))


class GuardTest(unittest.TestCase):
    def test_security_guards_pass(self):
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "security_guards.py")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def _order_guard(self, payload: str) -> int:
        return subprocess.run([sys.executable, str(ROOT / "tools" / "kite_order_guard.py")],
                              input=payload, capture_output=True, text=True).returncode

    def test_kite_order_guard_allows_read_modes_only(self):
        for mode in ("list", "history", "trades", "all_trades"):
            self.assertEqual(self._order_guard(json.dumps({"tool_input": {"mode": mode}})), 0, mode)
        for mode in ("place", "modify", "cancel", "approval_status", "permissions", "", None):
            self.assertEqual(self._order_guard(json.dumps({"tool_input": {"mode": mode}})), 2, mode)
        for payload in ("", "not json", "{}", "[]"):
            self.assertEqual(self._order_guard(payload), 2, payload)


if __name__ == "__main__":
    unittest.main()
