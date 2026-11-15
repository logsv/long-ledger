# India Stock Analyzer

A personal-use analysis workspace for long-term investors in Indian equities (NSE/BSE). It runs in [Claude Code](https://claude.com/claude-code):
- Claude fetches your broker records, reads documents and explains the results.
- A small, deterministic Python core stores the data and computes every number: labels, confidence, risk flags, caps and tax figures.

> **Analysis only.** The tool never places, modifies or cancels orders. You place every order yourself in your broker's app.
> Personal use only. Not investment or tax advice.

## Data sources

All data comes from your three brokers, read-only:

| Broker | How | What it provides |
|---|---|---|
| **Zerodha Kite** | Official MCP server (`mcp.kite.trade`) | Holdings, today's trades, daily prices, **index and India VIX history**, instrument names and ISINs |
| **INDmoney** | Official MCP server (`mcp.indmoney.com`, read-only by design) | Holdings, plus **asset class** (equity / gold / silver / liquid) and **market-cap bucket** (large / mid / small) for every holding across all linked brokers |
| **5paisa** | Xstream API, read-only client (`tools/isa.py fivepaisa`) | Holdings, today's trades, daily prices |

The brokers do **not** provide company financials, valuation, shareholding, pledge data or sectors. So the tool currently runs in **monitoring mode**: market conditions, allocation, risk flags and tax timing. Company scores and BUY/SELL labels stay off; stocks show `INSUFFICIENT_DATA`. They switch on automatically if company data is added later, through manual imports (`/import`) or a company-data source. Nothing needs rebuilding.

No data is collected from nseindia.com or bseindia.com automatically; their terms prohibit it.

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
- Broker reconciliation: broker quantities compared with your imported trade history.

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
  - FIFO lots per demat
  - STCG at 20% (s.196) and LTCG at 12.5% above ₹1.25 lakh (s.198), under the Income-tax Act, 2025
  - the long-term date for each lot, "wait until" hints, and the remaining exemption
- **HTML report:** one self-contained file.
- **Audit log:** append-only and hash-chained. Records every import, signal and decision.

**When company data is available** (manual imports today):
- **Scoring** on fundamentals, governance (red flags block a BUY) and valuation: own history, peers, and an intrinsic-value range with its assumptions shown.
- **Labels:** BUY / ACCUMULATE / HOLD / TRIM / SELL, with confidence and a plain-language "why".
- **Sell triggers:** your thesis conditions breaking, a 20% loss with weakening fundamentals, or valuation stretched above intrinsic value. A loss on its own never triggers a sell.

## Status

Version 0.3.0.

| Area | Status |
|---|---|
| Kite and INDmoney sync (MCP) | Built (`/sync`) |
| 5paisa sync (read-only API) | Built (`fivepaisa login` / `sync`) |
| INDmoney classification, ETF label, allocation limits | Built |
| Market regime from Kite index and VIX data | Built |
| Risk flags, timing, tax view, report, audit log | Built |
| Company scoring (fundamentals, governance, valuation) | Built. Waits for company data, which the brokers don't provide |
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
python3 -m unittest discover -s tests  # 48 tests
python3 tools/security_guards.py       # order tools blocked, secrets ignored
```

**Kite and INDmoney.** Open the folder in Claude Code and approve the project MCP servers (`kite`, `indmoney`). Run `/mcp` to sign in on each broker's own page.

**5paisa**, once:
1. Copy `.env.example` to `.env` and fill in `FIVEPAISA_USER_KEY`, `FIVEPAISA_USER_ID` and `FIVEPAISA_CLIENT_CODE` from the [Xstream dashboard](https://xstream.5paisa.com/dashboard). Register `http://127.0.0.1:8765/5paisa/callback` as the redirect URL if the dashboard allows it.
2. Store the encryption key in the Keychain. The command prompts for it, so it never appears on screen or in shell history:
   ```bash
   security add-generic-password -s india-stock-analyzer -a fivepaisa_encryption_key -w
   ```

**Trade history**, once: download each broker's tradebook (Kite Console, 5paisa and INDmoney reports) into `data/imports/` and run `/import`. After that, `/sync` adds new trades each day.

## Daily use

Kite and 5paisa sessions expire every day, which is a regulatory requirement, so each day starts with a sign-in on each broker's own page.

1. Sign in: `/mcp` for Kite and INDmoney, and `python3 tools/isa.py fivepaisa login` for 5paisa.
2. Run **`/sync`**. It pulls:
   - holdings, today's trades and prices from all three brokers
   - index and India VIX history from Kite
   - asset class and market cap from INDmoney
3. Run **`/portfolio`**, or **`/report`** for the HTML version: market regime, allocation, limit breaches, risk flags and tax waits.

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
python3 tools/isa.py import-trades --source kite --file data/imports/tradebook.csv
python3 tools/isa.py watch add HDFCBANK
python3 tools/isa.py decision HDFCBANK held --note "reviewed after results"
python3 tools/isa.py audit verify
```

File formats are described in [docs/DATA_FORMATS.md](docs/DATA_FORMATS.md).

## Configuration

All tunables are in `config/*.toml`:

| File | Contents |
|---|---|
| `thresholds.toml` | Limits (`max_stock_weight` 10%, `max_precious_metals_weight` 15%, `max_small_cap_weight` 60%, `max_sector_weight` 25%), loss trigger (20%), the `[market]` index list, `[monitor]` flag thresholds, governance limits |
| `weights.toml` | Block weights, label cut-offs, confidence settings |
| `valuation.toml` | DCF discount rate, terminal growth, growth caps |
| `tax.toml` | STCG/LTCG rates, the exemption and the holding period, each with its official source URL |

`.env` holds non-secret settings only (see `.env.example`). Secrets live in the macOS Keychain.

## Project layout

```
CLAUDE.md                 workspace rules and investor profile (read by Claude)
.mcp.json                 Kite and INDmoney MCP servers
.claude/settings.json     permissions: order tools denied, core CLI allowed
.claude/commands/         /sync /portfolio /report /sell-review /analyze /thesis /import
.claude/skills/           stock-analysis knowledge (rubric, governance, valuation, tax, trust boundary)
.claude/agents/           filing-reader, governance-checker, news-summarizer (read-only)
config/                   thresholds, weights, valuation assumptions, tax rules (TOML)
src/isa/
  brokers/                5paisa read-only client, macOS Keychain access
  importers/              holdings, trades, prices, classification, securities, facts
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
- **Untrusted data.** All broker output and imported files are treated as data, never as instructions.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).

## Disclaimer

This software is for the owner's personal research. It is not investment advice, research or tax advice, and it is not registered with SEBI as a Research Analyst or Investment Adviser. Do not share its output as recommendations. Broker market data is subject to the brokers' terms, for example Kite's ban on public display. Figures may be wrong; check them before acting.
