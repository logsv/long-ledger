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


class IndmoneyTaxReportTest(unittest.TestCase):
    def _xlsx(self, path, rows):
        """Write a minimal .xlsx with LTCG (empty) and STCG sheets using inline strings."""
        import zipfile
        from xml.sax.saxutils import escape

        def sheet(rs):
            body = "".join("<row>" + "".join(f'<c t="inlineStr"><is><t>{escape(str(v))}</t></is></c>' for v in r)
                           + "</row>" for r in rs)
            return ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    f"<sheetData>{body}</sheetData></worksheet>")
        wb = ('<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets>'
              '<sheet name="LTCG" sheetId="1"/><sheet name="STCG" sheetId="2"/></sheets></workbook>')
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("xl/workbook.xml", wb)
            z.writestr("xl/worksheets/sheet1.xml", sheet([["Client PAN:", "ABCDE1234F"]]))
            z.writestr("xl/worksheets/sheet2.xml", sheet(rows))

    def test_sales_become_buy_sell_pairs_and_dont_date_remaining_shares(self):
        import tempfile
        from isa.importers.indmoney_tax import import_tax_report
        hdr = ["Name of Stock", "ISIN", "Redemption date", "Purchase date", "Holding Period", "Units sold",
               "Per unit", "", "Total", "", "Gross Gains/Losses"]
        rows = [["Client PAN:", "ABCDE1234F"], ["STCG - Equity"], ["Indian Stocks"], hdr,
                ["", "", "", "", "", "", "Sell Value", "Purchase Value"], ["Gains"],
                ["ACME LTD", "INE000A01011", "2026-08-14", "2026-01-22", "<= 12 Months", "3", "120", "100",
                 "360", "300", "60"],
                ["Equity Mutual Funds"], ["Some Fund", "INF000A01011", "x"]]
        conn = db()
        import_securities(conn, [{"symbol": "ACME", "isin": "INE000A01011", "name": "Acme Ltd"}])
        import_holdings(conn, [{"symbol": "ACME", "quantity": 5, "average_price": 110}], "indmoney", as_of="2026-11-14")
        with tempfile.TemporaryDirectory() as d:
            self._xlsx(d + "/r.xlsx", rows)
            res = import_tax_report(conn, d + "/r.xlsx")
        self.assertEqual((res["sales_found"], res["stored"]), (1, 2))
        book = build_lots(conn, cfg().tax)
        self.assertEqual([(r.quantity, r.cost, r.term) for r in book.realised], [(3, 100, "STCG")])
        opening = [l for l in book.open_lots if l.estimated][0]
        self.assertEqual(opening.quantity, 5)            # the 5 still held are not dated by the report
        self.assertEqual(opening.acquired_before, "2026-11-14")
        pan = conn.execute("SELECT COUNT(*) FROM trade WHERE trade_id LIKE '%ABCDE1234F%'").fetchone()[0]
        self.assertEqual(pan, 0)


class CorporateActionTest(unittest.TestCase):
    def test_split_scales_earlier_lots_and_opening_lot_units(self):
        c = cfg()
        conn = db()
        # holding 100 today after a 1:2 split on 2026-07-01; history starts 2026-01-01
        import_holdings(conn, [{"symbol": "SPL", "quantity": 100, "average_price": 50}], "fivepaisa", as_of="2026-11-14")
        import_trades(conn, [trade("SPL", "sell", 10, 120, "2026-02-01", "1"),   # pre-split, old units
                             trade("SPL", "buy", 20, 100, "2026-03-01", "2"),    # pre-split, old units
                             trade("SPL", "buy", 10, 55, "2026-08-01", "3")], "fivepaisa")
        conn.execute("INSERT INTO corporate_action(symbol, ex_date, kind, ratio, source) VALUES ('SPL','2026-07-01','split',2,'t')")
        book = build_lots(conn, c.tax)
        total = sum(l.quantity for l in book.open_lots)
        self.assertAlmostEqual(total, 100)                       # reconciles in today's units
        bought = next(l for l in book.open_lots if l.buy_date == "2026-03-01")
        self.assertEqual((bought.quantity, bought.cost), (40, 50))  # 20 @100 -> 40 @50
        self.assertFalse(book.errors)                            # the pre-split sell matched the opening lot
        self.assertEqual(book.realised[0].quantity, 10)          # in old units, as traded

    def test_statement_events(self):
        import tempfile
        from isa.importers.fivepaisa_tx import import_statement
        conn = db()
        import_securities(conn, [{"symbol": "SWELECTES", "name": "SWELECT ENERGY SYSTEMS LTD"},
                                 {"symbol": "TDPOWERSYS", "name": "TD POWER SYSTEMS LTD"},
                                 {"symbol": "NIFTYBEES", "name": "Nippon India ETF Nifty 50 BeES"},
                                 {"symbol": "JUNIORBEES", "name": "Nippon India ETF Nifty Next 50 Junior BeES"}])
        import_trades(conn, [trade("TDPOWERSYS", "buy", 5, 800, "2026-02-03", "T1")], "fivepaisa")
        hdr = ["Transaction Date", "Company Name", "Exchange", "Type", "Quantity", "Price", "Tax/Charges",
               "Brokerage", "Remarks"]
        rows = [["EQUITY Transaction"], hdr,
                ["2026-02-03", "TD Power Systems", "NSE", "Buy", "5", "800", "0", "0", "Buy Trade"],      # covered
                ["2026-03-05", "Swelect Energy Syste", "NSE", "Buy", "7", "0", "0", "0", "OffMarket-In"],  # prefix
                ["2026-08-24", "TD Power Systems", "NSE", "Buy", "5", "0", "0", "0", "Split - 1.00:2.00"],
                ["2026-04-01", "Nifty BeES", "NSE", "Buy", "3", "250", "0", "0", "Buy Trade"],            # ambiguous
                ["Statement generated as on ..."]]
        with tempfile.TemporaryDirectory() as d:
            import csv
            with open(d + "/s.csv", "w", newline="") as fh:
                csv.writer(fh).writerows(rows)
            res = import_statement(conn, d + "/s.csv")
        self.assertEqual((res["trades_already_covered"], res["transfers_in"], res["splits"]), (1, 1, 1))
        self.assertEqual([u["name"] for u in res["unmatched_names"]], ["Nifty BeES"])  # two BeES ETFs: not guessed
        book = build_lots(conn, cfg().tax)
        x = next(l for l in book.open_lots if l.origin == "transfer_in")
        self.assertEqual((x.symbol, x.acquired_before, x.cost_known), ("SWELECTES", "2026-03-06", False))
        td = next(l for l in book.open_lots if l.symbol == "TDPOWERSYS")
        self.assertEqual((td.quantity, td.cost), (10, 400))


    def test_statement_name_map_symbol_not_yet_in_database(self):
        import csv
        import tempfile
        from pathlib import Path
        from isa.importers.fivepaisa_tx import import_statement
        conn = db()
        hdr = ["Transaction Date", "Company Name", "Exchange", "Type", "Quantity", "Price", "Tax/Charges",
               "Brokerage", "Remarks"]
        rows = [hdr,
                ["2025-06-02", "Thermax", "NSE", "Buy", "4", "3500", "0", "0", "Buy Trade"],
                ["2025-09-10", "Thermax", "NSE", "Sell", "4", "3700", "0", "0", "Sell Trade"],
                ["2026-07-01", "Vedanta Power", "NSE", "Buy", "25", "0", "0", "0", "Demerger-In"]]
        with tempfile.TemporaryDirectory() as d:
            with open(d + "/s.csv", "w", newline="") as fh:
                csv.writer(fh).writerows(rows)
            m = Path(d) / "name-map.csv"
            m.write_text("company_name,symbol\nThermax,thermax\nVedanta Power,VEDPOWER\n")
            res = import_statement(conn, d + "/s.csv", m)
            again = import_statement(conn, d + "/s.csv", m)
        self.assertEqual((res["trades"], res["demergers"], res["unmatched_names"]), (2, 1, []))
        self.assertEqual((again["trades"], again["duplicates"]), (0, 3))
        syms = {r[0] for r in conn.execute("SELECT symbol FROM security")}
        self.assertTrue({"THERMAX", "VEDPOWER"} <= syms)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM trade WHERE symbol = 'THERMAX'").fetchone()[0], 2)


class NameMapTest(unittest.TestCase):
    def test_two_column_name_map_loads(self):
        import tempfile
        from pathlib import Path
        from isa.importers.fivepaisa_tx import load_name_map
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "name-map.csv"
            p.write_text("company_name,symbol\nNifty BeES,NIFTYBEES\n")
            self.assertEqual(load_name_map(p), {"nifty bees": "NIFTYBEES"})
