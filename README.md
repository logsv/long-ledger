# India Stock Analyzer

A personal-use analysis workspace for long-term investors in Indian equities (NSE/BSE). It runs in [Claude Code](https://claude.com/claude-code):
- Claude fetches your broker records and reads company documents.
- A small, deterministic Python core stores the data and computes every signal: BUY / ACCUMULATE / HOLD / TRIM / SELL, with a confidence score, a plain-language "why", sell triggers, portfolio caps and a tax view.

> **Analysis only.** The tool never places, modifies or cancels orders. You place every order yourself in your broker's app.
> Personal use only. Not investment or tax advice.

## Features

- **Broker records, read-only.** Zerodha Kite and INDmoney come through their official MCP servers, with every order and GTT tool blocked. 5paisa comes through its Xstream API, using a client that can only call four read endpoints.
- **Manual-download imports.** Tradebooks, prices, sector lists, fundamentals exports, and annual-report or results PDFs. Claude extracts PDFs with page references, and each extracted figure waits for your confirmation.
- **Explainable scoring.** Fundamentals, governance (red flags veto BUY) and valuation, against the stock's own history, its peers and an intrinsic-value range with stated assumptions. Technicals change timing advice only.
- **Sell triggers:**
  - your own thesis conditions breaking
  - a 20% loss together with weakening fundamentals
  - valuation stretched above intrinsic value

  A loss on its own never triggers a sell.
- **Portfolio view.** Weights, allocation by asset class and market cap (from INDmoney), and cap breaches. The caps are 10% per stock, gold + silver 15%, small caps 60%, and 25% per sector when sectors exist. Also broker reconciliation.
- **Market and monitoring.** A market regime from Kite index and India VIX data, sector-index rotation, and per-stock risk flags: weak trend, deep drawdown, volume spike, loss from cost. Flags are review prompts, not signals.
- **Tax view.** FIFO lots per demat, STCG/LTCG under the Income-tax Act, 2025 (s.196 / s.198), the long-term date per lot, "wait until" hints and the remaining LTCG exemption.
- **Audit log.** Append-only and hash-chained. Records every import, signal and decision.
- **HTML report.** A single self-contained file.

## Status

Version 0.3.0.

| Area | Status |
|---|---|
| Kite and INDmoney sync via MCP | Built (`/sync`). INDmoney tool names are discovered at sign-in. |
| 5paisa | Built: read-only API (`fivepaisa login` / `sync`) for holdings, today's trades and daily prices. Older trades come from tradebook CSV. |
| Fundamentals, governance, valuation blocks | Built |
| Market regime (macro) block | Built from Kite index and India VIX data plus holdings breadth. Used only alongside company data |
| Broker-only monitoring | Built: INDmoney asset class and market cap, ETF label, risk flags, gold/silver and small-cap caps |
| Company data (financials, sector) | Not provided by Kite, 5paisa or INDmoney. Stocks stay INSUFFICIENT_DATA until a company-data source or manual imports are added |
| Sector and events blocks | Planned |
| CAS PDF parsing | Planned. Use broker tradebooks for now. |
| Loss set-off, 2018 grandfathering, STT | Not modelled. Tax figures are gross estimates. |
| Backtesting | Planned |

## Requirements

- Python 3.12 or newer. No third-party packages.
- Claude Code (desktop or CLI).
- A Zerodha and/or INDmoney account, for the MCP sign-in.

## Quick start

```bash
cd ~/Documents/india-stock-analyzer
python3 tools/isa.py init              # creates data/isa.db
python3 -m unittest discover -s tests  # 48 tests
python3 tools/security_guards.py       # order tools blocked, secrets ignored
```

Then open the folder in Claude Code:

1. Approve the project MCP servers (`indmoney`, `kite`) when asked. Run `/mcp` to sign in. Sign-in happens on each broker's own page, and both sessions expire daily.
2. Run `/sync` to pull holdings, today's trades and daily prices.
3. Put manual downloads into `data/imports/` and run `/import`. The first time, include your Kite Console tradebook so tax lots have buy dates.
4. Run `/portfolio`, `/analyze SYMBOL`, `/sell-review`, `/thesis SYMBOL` and `/report`.

## Slash commands

| Command | What it does |
|---|---|
| `/sync` | Kite and INDmoney (MCP) plus 5paisa (API) holdings, trades and prices into the database |
| `/import` | Load files from `data/imports/`; PDFs go through the `filing-reader` and `governance-checker` subagents; confirm extracted facts |
| `/portfolio` | Score holdings and watchlist; show labels, triggers, caps, tax waits |
| `/analyze SYMBOL` | Full breakdown: every evidence line, valuation assumptions, timing, tax lots |
| `/sell-review` | Holdings with sell triggers, with lot-by-lot tax impact |
| `/thesis SYMBOL` | Write or review checkable thesis conditions |
| `/report` | Write the HTML report to `data/reports/` |

## Core CLI

Claude calls the core through `tools/isa.py`. You can call it too. Every command prints JSON.

```bash
python3 tools/isa.py --help
python3 tools/isa.py import-trades --source kite --file data/imports/tradebook.csv
python3 tools/isa.py watch add HDFCBANK
python3 tools/isa.py thesis add HDFCBANK roe '>=' 15 --note "returns stay above 15%"
python3 tools/isa.py portfolio
python3 tools/isa.py analyze HDFCBANK --no-record
python3 tools/isa.py tax
python3 tools/isa.py report
python3 tools/isa.py audit verify
python3 tools/isa.py fivepaisa status   # then: fivepaisa login, fivepaisa sync
```

**5paisa setup, once:**
1. Copy `.env.example` to `.env` and fill in `FIVEPAISA_USER_KEY`, `FIVEPAISA_USER_ID` and `FIVEPAISA_CLIENT_CODE` from the [Xstream dashboard](https://xstream.5paisa.com/dashboard). Register `http://127.0.0.1:8765/5paisa/callback` as the redirect URL if the dashboard allows it.
2. Store the encryption key in the Keychain. The command prompts for it, so it never appears on screen or in shell history:

```bash
security add-generic-password -s india-stock-analyzer -a fivepaisa_encryption_key -w
```

File formats are described in [docs/DATA_FORMATS.md](docs/DATA_FORMATS.md).

## Project layout

```
CLAUDE.md                 workspace rules and investor profile (read by Claude)
.mcp.json                 Kite and INDmoney MCP servers
.claude/settings.json     permissions: order tools denied, core CLI allowed
.claude/commands/         /sync /import /portfolio /analyze /sell-review /thesis /report
.claude/skills/           stock-analysis knowledge (rubric, governance, valuation, tax, trust boundary)
.claude/agents/           filing-reader, governance-checker, news-summarizer (read-only)
config/                   weights, thresholds, valuation assumptions, tax rules (TOML)
src/isa/                  deterministic core: storage, importers, engine, tax, portfolio, report, audit
tools/                    isa.py (CLI), security_guards.py
tests/                    unit and end-to-end tests (synthetic data)
data/                     git-ignored: isa.db, imports/, reports/
```

How the pieces fit is described in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Configuration

All tunables are in `config/*.toml`:

| File | Contents |
|---|---|
| `weights.toml` | Block weights, label cut-offs, confidence settings |
| `thresholds.toml` | Loss trigger (20%), caps (10% / 25%), governance limits, index symbol for relative strength |
| `valuation.toml` | DCF discount rate, terminal growth, growth caps |
| `tax.toml` | STCG/LTCG rates, the exemption and the holding period, each with its official source URL |

`.env.example` lists the optional environment settings. Secrets never go in `.env`.

## Safety

See [SECURITY.md](SECURITY.md). In short:
- Order and GTT tools are denied, and a CI guard enforces it.
- No secrets in the repo, and Claude cannot read `.env`.
- No automated access to nseindia.com or bseindia.com, which their terms prohibit.
- All imported content is treated as untrusted data.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).

## Disclaimer

This software is for the owner's personal research. It is not investment advice, research or tax advice, and it is not registered with SEBI as a Research Analyst or Investment Adviser. Do not share its output as recommendations. Market data from brokers is subject to their terms, for example Kite's ban on public display. Figures may be wrong; check them before acting.
