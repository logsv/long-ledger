# Data formats

Every importer accepts **JSON** or **CSV**:
- JSON can be a list of objects, or an object wrapping one list (e.g. `{"data": [...]}`).
- Column names are matched case-insensitively, with common broker aliases.
- Dates may be `YYYY-MM-DD`, `DD-MM-YYYY`, `YYYY-MM-DD HH:MM:SS`, or 5paisa's `/Date(ms+0530)/`.
- Rows that fail validation are skipped and reported. They are never guessed.

Put files in `data/imports/` (git-ignored). `/sync` writes MCP results to `data/imports/mcp/`.

## Holdings: `import-holdings --source kite|indmoney|fivepaisa|manual [--as-of DATE]`

| Field | Aliases |
|---|---|
| symbol | `tradingsymbol`, `symbol`, `ScripName`, `ticker` |
| quantity | `quantity`, `qty`, `Quantity` (Kite `t1_quantity` is added) |
| average price | `average_price`, `avg_price`, `AvgRate`, `buy_avg` |
| last price | `last_price`, `ltp`, `CurrentPrice` |
| isin, exchange, name | optional |

Each import is a snapshot for `as_of` (default: today) per source. Portfolio quantities come from each broker's latest snapshot.

## Trades: `import-trades --source ... [--account NAME]`

| Field | Aliases |
|---|---|
| symbol | as above |
| side | `trade_type`, `transaction_type`, `BuySell` (`buy`/`sell`/`B`/`S`) |
| quantity | `quantity`, `Qty` |
| price | `price`, `average_price`, `Rate` |
| date | `trade_date`, `fill_timestamp`, `ExchangeTradeTime` |
| trade id | `trade_id`, `ExchangeTradeID` |

- Kite Console tradebook CSV works as exported.
- Rows whose product or segment is not delivery equity are skipped: anything other than CNC, D or EQ, such as MIS, intraday or F&O.
- Without a trade id, a stable id is derived, so re-importing the same file creates no duplicates.
- Lots are matched FIFO **per account**, which defaults to the source.

## Prices: `import-prices --symbol SYM --source NAME [--index]`

Columns: `date, open, high, low, close, volume`. Kite's raw candle arrays `[date, o, h, l, c, v]` also work.
- Use `--index` for an index such as `NIFTY 500`, which enables relative strength.
- A file with a `symbol` column can hold several stocks; leave out `--symbol`.

## Classification: `import-classification --file <INDmoney reply> [--map keys.json]`

Pass INDmoney's net-worth/holdings MCP reply as saved: either `{"result": "<json>"}` or JSON with a `holdings` list. Each row has `investment_code`, `investment`, `assetclass_l2` and `market_cap`.
- Rows are matched to your securities by a stored INDmoney key, by `--map` (`[{"ind_key", "symbol" | "isin"}]`, built with INDmoney's lookup tool), or by an exact company name.
- Unmatched rows are listed, never guessed.
- ETFs (non-equity asset class, or a name containing ETF or BeES) get `is_etf = 1` and no market-cap bucket.

## Securities: `import-securities`

Columns: `symbol, isin, name, exchange, sector, industry`.
- Sector drives the sector caps.
- Industry (or sector, when industry is not set) defines the valuation peers.
- Or set one stock at a time: `python3 tools/isa.py security SYM --sector "..." --industry "..."`.

## Facts: `import-facts --source NAME [--extracted-by import|user|llm]`

Long format, one number per row:

```
symbol,metric,period_end,published_at,value,source_ref
HDFCBANK,pat,2026-03-31,2026-04-19,70000,annual-report-FY26.pdf p.212
HDFCBANK,promoter_pct,2026-09-30,2026-10-15,0,shareholding Q2FY27
```

- **`published_at`** is the date the number became public. The engine never uses a fact before this date (point-in-time).
- Amounts are in **INR crore**; shares in **crore**; percentages are plain numbers (12.5 means 12.5%); flags are 0 or 1.
- `--extracted-by llm` facts **must** have a `source_ref` and stay pending until `confirm-facts`.
- For the same period, user and import figures take precedence over LLM figures.

Run `python3 tools/isa.py metrics` for the full catalogue:

| Group | Metrics |
|---|---|
| Annual financials | `revenue`, `ebitda`, `ebit`, `pat`, `eps`, `total_equity`, `total_debt`, `cash`, `interest_expense`, `cfo`, `capex` (positive), `dividend_per_share`, `shares_outstanding` |
| Working capital | `receivable_days`, `inventory_days`, `payable_days` |
| Governance | `rpt_pct_revenue`, `auditor_qualified`, `auditor_resigned` |
| Shareholding (quarterly) | `promoter_pct`, `promoter_pledge_pct`, `fii_pct`, `dii_pct`, `mf_pct` |

## Thesis conditions: `thesis add SYMBOL METRIC OP THRESHOLD [--note TEXT]`

- `METRIC` is any evidence key the engine shows (`revenue_cagr_3y`, `roce`, `debt_to_equity`, `promoter_pledge_pct`, …) or a raw fact metric.
- `OP` is one of `> >= < <=`. Quote it in the shell.
- When a condition fails, the stock gets a `thesis_broken` trigger.
