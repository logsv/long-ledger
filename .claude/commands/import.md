# /import: load manual downloads from data/imports/

The user downloads files by hand: broker tradebooks, CAS statements, NSE/BSE files, Screener/Tijori exports, annual reports and results. Never fetch from nseindia.com or bseindia.com yourself.

`$ARGUMENTS` may be a file name or a folder. The default is everything new in `data/imports/` (skip the `mcp/` subfolder; `/sync` owns it).

## Step 1: Identify each file
Look at the name, header row or first page, then route it:

| File | Command |
|---|---|
| Kite Console tradebook CSV (`symbol, isin, trade_date, ... trade_type, quantity, price, trade_id`) | `python3 tools/isa.py import-trades --source kite --file <f>` |
| 5paisa tradebook CSV/JSON | `python3 tools/isa.py import-trades --source fivepaisa --file <f>` |
| INDmoney trade/P&L export | `python3 tools/isa.py import-trades --source indmoney --file <f>` |
| Daily price CSV (`date, open, high, low, close, volume`) | `python3 tools/isa.py import-prices --symbol <SYM> --source manual --file <f>` (add `--index` for an index) |
| Sector/industry list (`symbol, isin, name, exchange, sector, industry`) | `python3 tools/isa.py import-securities --file <f>` |
| Fundamentals already in long format (`symbol, metric, period_end, published_at, value`) | `python3 tools/isa.py import-facts --source <export-name> --extracted-by import --file <f>` |
| Wide spreadsheet export (years as columns) | Rewrite it to long format with **exact** values into `data/imports/facts-<SYM>-<date>.csv`, then import it with `--extracted-by import`. Tell the user you converted it. |
| Annual report, results PDF, shareholding pattern PDF | Dispatch the **filing-reader** subagent (below) |
| CAS PDF | Not parsed automatically yet. Ask the user for the broker tradebooks instead, or read the holdings table with filing-reader and import it as holdings with `--source manual` |

`python3 tools/isa.py metrics` lists the accepted metric names and units: crore for amounts, plain numbers for percentages.

**Spreadsheets:** `.xlsx` files are read directly; there's no need to convert them. Title rows above the header and footer lines are skipped.
- **5paisa:** use the **Trade Listing** report (it has ISIN and trade numbers). Not the "EQUITY Transaction" report, which has neither, so it can't be matched or de-duplicated.
- **INDmoney consolidated tax report** (`consolidated_tax_report_<FY>.xlsx`): run `python3 tools/isa.py import-indmoney-tax --file <f>`.
  - Each realised Indian stock or ETF sale becomes a buy and a sell with exact dates and prices.
  - Only the Indian Stocks and ETF sections are read. The client name and PAN header, mutual funds, US stocks and foreign-asset sheets are ignored.
  - It covers only shares already sold, so INDmoney's current holdings keep estimated dates until a trade-history export is imported.
  - Never quote the PAN or other personal details from this file.

**Unknown ISINs:** if an import returns `unknown_isins`, those stocks aren't in the database yet. They are usually shares you've sold.
1. Look each ISIN up with `mcp__kite__search_instruments` (`filter_on: "isin"`).
2. Write a CSV `symbol,isin,name` with the values **exactly as returned** to `data/imports/mcp/isin-lookup-<date>.csv`.
3. Run `python3 tools/isa.py import-securities --file <that file>`.
4. Re-import the same trade file. Duplicates are skipped, so only the missing rows are added.

## Step 2: PDFs through filing-reader
For each PDF, dispatch the `filing-reader` subagent with the file path, the symbol, and the `metrics` list.
- It returns a JSON array of facts, each with a `source_ref` (file name and page).
- Save the array to `data/imports/extracted-<SYM>-<date>.json` and run `python3 tools/isa.py import-facts --source <document-name> --extracted-by llm --file <that file>`.
- These facts stay **pending**: the engine ignores them until confirmed.
- For related-party transactions, auditor remarks and resignations, also dispatch `governance-checker` and import what it returns the same way.

## Step 3: Confirm extracted facts
Run `python3 tools/isa.py pending-facts` and show them grouped by stock: metric, period, value, `source_ref`.
- Ask the user which to confirm. They may check a few against the PDF page.
- Run `python3 tools/isa.py confirm-facts <ids...>` only for the IDs the user approved.

## Step 4: Report
Show what was stored, any skipped rows with their reasons, and what is still pending. Suggest `/portfolio`.
