# India Stock Analyzer

A personal-use analysis workspace for long-term investors in Indian equities (NSE/BSE). It runs in [Claude Code](https://claude.com/claude-code):
- Claude fetches your broker records, reads documents and explains the results.
- A small, deterministic Python core stores the data and computes every number: labels, confidence, risk flags, caps and tax figures.

> **Analysis only.** The tool never places, modifies or cancels orders. You place every order yourself in your broker's app.
> Personal use only. Not investment or tax advice.

## Data sources

Data comes from your three brokers (read-only) and from listed companies' own websites:

| Source | How | What it provides |
|---|---|---|
| **Zerodha Kite** | Official MCP server (`mcp.kite.trade`) | Holdings, today's trades, daily prices, **index and India VIX history**, instrument names and ISINs |
| **INDmoney** | Official MCP server (`mcp.indmoney.com`, read-only by design) | Holdings, plus **asset class** (equity / gold / silver / liquid) and **market-cap bucket** (large / mid / small) for every holding across all linked brokers |
| **5paisa** | Xstream API, read-only client (`tools/isa.py fivepaisa`) | Holdings, today's trades, daily prices |
| **Company websites** | `/research`: Claude web search and fetch, limited to each company's own investor-relations pages | Annual financials, quarterly shareholding and pledge, auditor opinion, related-party transactions, sector |

The brokers do **not** provide company financials, valuation, shareholding, pledge data or sectors. Those come from **`/research`**:
- A read-only subagent finds each company's official website and reads its annual reports, results and shareholding filings.
- Every number is stored with its source URL and page.
- `check-facts` tests each document for unit errors (lakh vs crore), EPS ≠ PAT ÷ shares, EBIT above EBITDA, impossible percentages and revenue jumps.
- Documents that pass are confirmed automatically. Set `auto_confirm_checked = false` to confirm them yourself. Documents with issues stay pending.

Until a company has confirmed data it is in **monitoring mode**: market conditions, allocation, risk flags and tax timing, with no BUY/SELL label.

Research never reads nseindia.com, bseindia.com, screener.in, tijorifinance.com, trendlyne.com, moneycontrol.com or tickertape.in. Their terms forbid automated collection, or they are second-hand aggregators. These domains are denied in `.claude/settings.json`, and the safety guard checks it.

## What you get

**Market regime**
- The NIFTY 500 and NIFTY 50 trend against their 200-day averages.
- Where India VIX sits against its last year.
- Breadth: how many of your stocks are above their 200-day average.
- Sector-index leaders and laggards over 3 and 6 months.

**Allocation and limits**
- Weights by stock, asset class and market cap.
- Limits:
  - 10% per stock
  - gold + silver 15%
  - small caps 60%
  - 25% per sector, when sectors are known
- Broker reconciliation: each broker's quantity per stock compared with your imported trade history. Gaps are explained (estimated opening lots, transfers) instead of left as mismatches.

**Risk flags per stock.** These are review prompts, not sell signals.

| Flag | When it appears |
|---|---|
| `weak_trend` | Below the 200-day average and trailing the NIFTY 500 by 10 or more points over 6 months |
| `deep_drawdown` | 25% or more below the 52-week high |
| `volume_spike` | 20-day volume at least 2× normal |
| `loss_from_cost` | Down 20% or more from your average cost |

**Also included**
- **ETF label** for gold, silver, liquid and index ETFs, which company analysis doesn't apply to.
- **Timing view:** 50/200-day averages, relative strength, support and resistance, drawdown.
- **Tax view:**
  - FIFO lots per demat; a sale only matches shares bought on or before its date
  - STCG at 20% (s.196) and LTCG at 12.5% above ₹1.25 lakh (s.198), under the Income-tax Act, 2025
  - the long-term date for each lot, "wait until" hints, and the remaining exemption
  - stock splits and bonuses applied to earlier lots in every account
  - each lot shows where it came from:

    | Lot origin | Meaning |
    |---|---|
    | `trade` | An exact buy from a tradebook |
    | `opening` | Bought before your earliest imported trade; shown as "before <date>" |
    | `transfer_in` | Moved in off-market; the original buy date is unknown |
    | `demerger` | Shares from a demerger; cost to be apportioned per the company's notice |

    Unknown terms are taxed at the STCG rate as a worst case.
- **HTML report:** one self-contained file. Each holding shows its company name, the brokers holding it with quantities, flags, trend and company-data coverage.
- **Audit log:** append-only and hash-chained. Records every import, signal and decision.

**For each company with confirmed data** (from `/research` or `/import`):
- **Scoring** on fundamentals, governance (red flags block a BUY) and valuation: own history, peers, and an intrinsic-value range with its assumptions shown.
- **Labels:** BUY / ACCUMULATE / HOLD / TRIM / SELL, with confidence and a plain-language "why".
- **Sell triggers:** your thesis conditions breaking, a 20% loss with weakening fundamentals, or valuation stretched above intrinsic value. A loss on its own never triggers a sell.

## Status

Version 0.6.2.

| Area | Status |
|---|---|
| Kite and INDmoney sync (MCP) | Built (`/sync`) |
| 5paisa sync (read-only API) | Built (`fivepaisa login` / `sync`) |
| INDmoney classification, ETF label, allocation limits | Built |
| Market regime from Kite index and VIX data | Built |
| Risk flags, timing, tax view, report, audit log | Built |
| Trade history imports | Built: Kite tradebook (CSV/XLSX); 5paisa Trade Listing and EQUITY Transaction statement; INDmoney consolidated tax report. Splits, off-market transfers and demergers are handled |
| INDmoney full trade history | Not available yet. The tax report covers sold shares only, so current INDmoney holdings keep estimated dates |
| Company data from company websites (`/research`) | Built: research subagent, fact checks, automatic confirmation of clean documents |
| Company scoring (fundamentals, governance, valuation) | Built. Active for each company once its data is confirmed |
| Sector and events blocks | Planned |
| CAS PDF parsing | Planned. Use broker tradebooks |
| Loss set-off, 2018 grandfathering, STT | Not modelled. Tax figures are gross estimates |
| Backtesting | Planned |

## Requirements

- macOS (the Keychain holds the 5paisa secrets) with Python 3.12 or newer. No third-party packages.
- Claude Code (desktop or CLI).
- Accounts with Zerodha, INDmoney and/or 5paisa.

## Setup

```bash
cd ~/Documents/india-stock-analyzer
python3 tools/isa.py init              # creates data/isa.db (migrates older databases)
python3 -m unittest discover -s tests  # 58 tests
python3 tools/security_guards.py       # order tools blocked, secrets ignored
```

**Kite and INDmoney.** Open the folder in Claude Code and approve the project MCP servers (`kite`, `indmoney`). Run `/mcp` to sign in on each broker's own page.

**5paisa**, once:
1. Copy `.env.example` to `.env` and fill in `FIVEPAISA_USER_KEY`, `FIVEPAISA_USER_ID` and `FIVEPAISA_CLIENT_CODE` from the [Xstream dashboard](https://xstream.5paisa.com/dashboard). Register `http://127.0.0.1:8765/5paisa/callback` as the redirect URL if the dashboard allows it.
2. Store the encryption key in the Keychain. The command prompts for it, so it never appears on screen or in shell history:
   ```bash
   security add-generic-password -s india-stock-analyzer -a fivepaisa_encryption_key -w
   ```

**Trade history**, once: download into `data/imports/` and run `/import`. `.xlsx` and `.csv` files are read directly, and re-importing a file never creates duplicates.
- **Kite:** Console → Reports → Tradebook → Equity. One file per financial year (01-04 to 31-03), back to your oldest holding.
  - After changing the dates, **click the arrow button** and check the table shows that year before exporting. Otherwise Console exports the current year again.
  - Every year downloads with the same file name, so rename each one (for example `tradebook-FY2025-26.xlsx`).
- **5paisa:**
  - the **Trade Listing** report (exact trades, with ISIN and trade numbers), back to your account opening
  - then the **EQUITY Transaction** statement, which adds splits, off-market transfers in and demerger shares
  - 5paisa shortens company names. Names that can't be matched exactly are listed, and you confirm their symbols in `data/imports/name-map.csv` (`company_name,symbol`).
- **INDmoney:** the **consolidated tax report** (.xlsx, one per financial year).
  - `/import` turns every realised Indian stock and ETF sale into a buy and a sell with exact dates.
  - Your name and PAN are never read.
  - It doesn't cover shares you still hold. A trade-history export from INDmoney would add those.

Shares bought before your earliest imported trade become **estimated opening lots**: quantities reconcile, but their buy date shows as "before <date>". Import older tradebooks to replace them with exact lots. After that, `/sync` adds new trades each day.

**Company data**, first run:
1. Run `/research --top 5` and review the result: sources, confirmed documents, anything pending.
2. Then run `/research --top 20`. The top 20 holdings cover most of the portfolio's value.
3. Holdings beyond those can follow in later runs.

## Daily use

Kite and 5paisa sessions expire every day, which is a regulatory requirement, so each day starts with a sign-in on each broker's own page.

1. Sign in: `/mcp` for Kite and INDmoney, and `python3 tools/isa.py fivepaisa login` for 5paisa.
2. Run **`/sync`**. It pulls:
   - holdings, today's trades and prices from all three brokers
   - index and India VIX history from Kite
   - asset class and market cap from INDmoney
3. Run **`/portfolio`**, or **`/report`** for the HTML version: market regime, allocation, limit breaches, labels, risk flags and tax waits.

Company data changes quarterly, not daily. Run **`/research`** once for your top holdings (`--top 20`), then `/research --refresh` after each results season.

Run `/sync` on every trading day you trade. The APIs only return that day's trades, and a missed day shows up as a reconciliation warning.

## Slash commands

| Command | What it does |
|---|---|
| `/sync` | All three brokers, plus Kite indices and VIX, plus INDmoney classification, into the database |
| `/portfolio` | Market regime, allocation and limits, labels, risk flags, tax waits |
| `/report` | Writes the HTML report to `data/reports/` |
| `/sell-review` | Holdings with triggers or flags, with lot-by-lot tax impact |
| `/analyze SYMBOL` | Full breakdown for one stock: evidence, timing, flags, tax lots |
| `/thesis SYMBOL` | Write or review checkable thesis conditions (used once company data exists) |
| `/research [--top N] [--refresh] [SYMBOLS or "company names"]` | Company financials, shareholding, pledge, auditor opinion and sector from companies' own websites, checked and stored with sources |
| `/import` | Load manual downloads from `data/imports/`: tradebooks, prices, company data, PDFs |

## Core CLI

Claude calls the core through `tools/isa.py`. You can call it too. Every command prints JSON.

```bash
python3 tools/isa.py --help
python3 tools/isa.py portfolio --no-record      # monitoring view without storing signals
python3 tools/isa.py market                     # regime, indices, VIX, breadth, sector rotation
python3 tools/isa.py tax                        # lots, terms, wait dates, exemption left
python3 tools/isa.py report
python3 tools/isa.py fivepaisa status           # then: fivepaisa login, fivepaisa sync
python3 tools/isa.py import-classification --file data/imports/mcp/indmoney-networth-holdings-raw-<date>.json
python3 tools/isa.py import-trades --source kite --file data/imports/tradebook-FY2025-26.xlsx
python3 tools/isa.py import-trades --source fivepaisa --file data/imports/Tradelisting_<...>.xlsx
python3 tools/isa.py import-5paisa-statement --file data/imports/EQUITY_Transaction_<...>.xlsx
python3 tools/isa.py import-indmoney-tax --file "data/imports/consolidated_tax_report_2026-27.xlsx"
python3 tools/isa.py research-targets --top 20     # what /research will fetch next
python3 tools/isa.py research-targets "Hero MotoCorp" SANGHVIMOV
python3 tools/isa.py coverage                      # company data per holding
python3 tools/isa.py check-facts --symbol SANGHVIMOV
python3 tools/isa.py confirm-facts --source SANGHVIMOV-AR-FY2026
python3 tools/isa.py watch add HDFCBANK
python3 tools/isa.py decision HDFCBANK held --note "reviewed after results"
python3 tools/isa.py audit verify
```

File formats are described in [docs/DATA_FORMATS.md](docs/DATA_FORMATS.md).

## Configuration

All tunables are in `config/*.toml`:

| File | Contents |
|---|---|
| `thresholds.toml` | `[research] auto_confirm_checked`, limits (`max_stock_weight` 10%, `max_precious_metals_weight` 15%, `max_small_cap_weight` 60%, `max_sector_weight` 25%), loss trigger (20%), the `[market]` index list, `[monitor]` flag thresholds, governance limits |
| `weights.toml` | Block weights, label cut-offs, confidence settings |
| `valuation.toml` | DCF discount rate, terminal growth, growth caps |
| `tax.toml` | STCG/LTCG rates, the exemption and the holding period, each with its official source URL |

`.env` holds non-secret settings only (see `.env.example`). Secrets live in the macOS Keychain.

## Project layout

```
CLAUDE.md                 workspace rules and investor profile (read by Claude)
.mcp.json                 Kite and INDmoney MCP servers
.claude/settings.json     permissions: order tools denied, core CLI allowed
.claude/commands/         /sync /research /portfolio /report /sell-review /analyze /thesis /import
.claude/skills/           stock-analysis knowledge (rubric, governance, valuation, tax, trust boundary)
.claude/agents/           company-researcher, filing-reader, governance-checker, news-summarizer (read-only)
config/                   thresholds, weights, valuation assumptions, tax rules (TOML)
src/isa/
  brokers/                5paisa read-only client, macOS Keychain access
  importers/              holdings, trades (CSV/XLSX), 5paisa statement, INDmoney tax report,
                          prices, classification, securities, facts
  engine/                 market regime, monitor flags, technicals, fundamentals, governance, valuation, scoring
  tax/  portfolio/        FIFO lots and STCG/LTCG; allocation, limits, reconciliation
  report/  audit/         HTML report; hash-chained audit log
tools/                    isa.py (CLI), security_guards.py
tests/                    unit and end-to-end tests (synthetic data only)
data/                     git-ignored: isa.db, imports/, reports/
```

How the pieces fit is described in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Safety

See [SECURITY.md](SECURITY.md). In short:
- **No orders, in four layers:** every broker order and GTT tool is denied in `.claude/settings.json`; the 5paisa client can only call read endpoints; no order code exists anywhere; and `tools/security_guards.py` checks all of this in CI.
- **No secrets in the repo.** Claude cannot read `.env`. 5paisa keys and tokens stay in the Keychain.
- **Web research is limited to company websites.** Exchange and aggregator domains are denied. Searches carry company names only. Documents are confirmed automatically only if every consistency check passes.
- **Untrusted data.** All broker output, web pages and imported files are treated as data, never as instructions.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).

## Disclaimer

This software is for the owner's personal research. It is not investment advice, research or tax advice, and it is not registered with SEBI as a Research Analyst or Investment Adviser. Do not share its output as recommendations. Broker market data is subject to the brokers' terms, for example Kite's ban on public display. Figures may be wrong; check them before acting.
