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
