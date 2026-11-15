# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [0.7.1] - 2026-11-15

### Changed
- **The dashboard code is no longer in the repository.** Commit `9988d68` is reverted; the code is now **git-ignored and kept on this machine only**.
  - Ignored paths: `src/isa/web/`, `tools/dashboard.py`, `tests/test_web.py`.
  - The `serve` CLI command is gone; start the dashboard with `python3 tools/dashboard.py` or `/dashboard`.
  - The dashboard registers its own `ui_action` audit event type.
  - The `/dashboard` command, the skill file and this documentation stay in git.

## [0.7.0] - 2026-11-15

### Added
- **Local dashboard** (http://127.0.0.1:8770). Its code moved out of git in 0.7.1.
  - Built from a standard-library server and Tabulator 6.3.1 (MIT), stored locally after downloading it with bun.
  - **Tabs:** Overview, Holdings, Trades, Tax lots, Data quality.
  - **Tables:** column filters, search, quick filters, grouping with subtotals, CSV export, and click-through from a holding to its trades and lots.
  - **Buttons:** Refresh, Recompute signals, Export HTML report, 5paisa sync.
- **Security:**
  - loopback-only binding and Host-header check
  - read-only data views
  - a per-run action token and Origin check
  - a strict CSP
  - `ui_action` audit events
  - a new `security_guards.py` check
- 8 server tests (66 in total).

## [0.6.2] - 2026-11-15

### Added
- **"Brokers" column** in the report's holdings table. It lists each broker holding the stock with its quantity, for example "Zerodha 340, INDmoney 377". The portfolio JSON gains `by_account`.

## [0.6.1] - 2026-11-15

### Fixed
- **Column matching** ignores case, spaces and underscores, so Kite Console's `.xlsx` tradebook ("Trade ID", "Trade Type") imports like its CSV.
- **The two-column `name-map.csv` loads correctly.**

## [0.6.0] - 2026-11-15

### Added
- **`import-5paisa-statement`:** the 5paisa EQUITY Transaction statement.
  - **Splits and bonuses** are recorded as corporate actions (schema v3) and applied to lots in every account.
  - **Off-market transfers in** become lots with an unknown original buy date.
  - **Demerger shares** become lots with an unknown cost.
  - **Trades** are added only for days the Trade Listing doesn't cover.
  - **Company names** are matched deterministically, with an optional `name-map.csv`.
- **Lot origins:** `trade`, `opening`, `transfer_in`, `demerger`. Reconciliation reports transfer and demerger lots separately.
- **Tax view:** shows "cost unknown" for demerger lots.

### Fixed
- **Estimated opening lots** are now expressed in the share count of their date. Pre-split sells match them correctly, and later splits scale them.

## [0.5.1] - 2026-11-15

### Added
- **`import-indmoney-tax`:** INDmoney consolidated tax reports.
  - Every realised Indian stock and ETF sale becomes a BUY + SELL pair with exact dates and prices.
  - The FY 2026-27 totals match the report summary exactly (sell ₹1,09,366, buy ₹75,188).
  - The name, PAN and non-equity sheets are ignored.
- **`.xlsx` reader** can pick a sheet by name.

### Fixed
- **FIFO only matches a sale to lots bought on or before the sale date.** Before this, an estimated opening lot dated after a sale could absorb it.
- **Tax-report trades no longer set an account's history start date,** because they cover sold shares only.

## [0.5.0] - 2026-11-15

### Added
- **`/research` by company name:** `research-targets "Hero MotoCorp" SANGHVIMOV ...`. Names resolve to known stocks; vague or ambiguous names are returned for you to choose; new companies are identified by the researcher and added to the watchlist.
- **`coverage` command.**
- **Report:**
  - a company name under each symbol
  - a "Company data" column (years stored, latest shareholding quarter, source site, pending facts)
  - a summary card for coverage by value
  - "before <date> (est.)" for opening lots
  - an alert for sells with no earlier buy
- **Native `.xlsx` import** (standard library only), with header-row detection and Excel serial dates.
- **5paisa Trade Listing format:** Buy Qty / Sell Qty, Trade No, Market Rate.
  - Symbols are resolved by ISIN, or by an exact company-name match that also records the ISIN.
  - Unknown ISINs are listed so `/import` can look them up through Kite.
- **Estimated opening lots** for shares held before the earliest imported trade.
  - Broker quantities now reconcile.
  - Their term is `unknown` until 12 months after the latest possible buy date, and they're taxed at the STCG rate as a worst case.
- **INDmoney average cost** from `invested_amount`.

### Fixed
- A trade number repeated on different rows of one file is no longer dropped as a duplicate.

## [0.4.0] - 2026-11-15

### Added
- **`/research`**: automated company data from companies' own websites.
  - Gathers annual financials, quarterly shareholding and pledge, auditor opinion, related-party transactions and sector.
  - Done by the new read-only `company-researcher` subagent.
- **`check-facts`**: unit and consistency checks (EPS vs PAT ÷ shares, EBIT ≤ EBITDA ≤ revenue, % ranges, revenue jumps).
- **`confirm-facts --source DOC`**: confirms a whole document, refusing any document with issues. `[research] auto_confirm_checked` (default true) confirms clean documents automatically.
- **`research-targets`**: a work queue by portfolio weight.
- **Exchange and aggregator domains** denied for WebFetch in settings, enforced by the guard.
- 51 tests in total.

## [0.3.0] - 2026-11-15

### Added
- **Broker-only monitoring.** Data comes only from Kite, INDmoney and 5paisa.
  - **Classification from INDmoney** (`import-classification`): asset class, market-cap bucket and ETF flag for every holding across brokers. Rows are matched by stored INDmoney key, ISIN mapping or exact company name.
  - **Market regime block (a)** from Kite index data: NIFTY 500 and NIFTY 50 against their 200-DMA, India VIX percentile, breadth of your holdings, and sector-index rotation. It counts in the composite only when company data exists.
  - **Monitoring flags:** `weak_trend`, `deep_drawdown`, `volume_spike`, `loss_from_cost`. These are review prompts, never labels.
  - **ETF label** for gold, silver, liquid and index ETFs.
  - **New caps:** gold + silver at 15% and small caps at 60% (defaults in `config/thresholds.toml`).
  - **Report:** market and allocation sections.
- `/sync` now also pulls index and VIX history and INDmoney's classification.
- `market` CLI command.
- Schema v2 with automatic migration.
- 48 tests in total.

## [0.2.0] - 2026-11-15

### Added
- **5paisa Xstream API client** (read-only): `fivepaisa status | login | token | sync | logout`.
  - Covers holdings, today's delivery trades and daily cash-segment candles.
  - Login uses 5paisa's own page with a 127.0.0.1 callback that checks `state`.
  - The encryption key and access token live in the macOS Keychain.
  - An endpoint allowlist is enforced by the client and by `security_guards.py`.
- `.env` loading for non-secret settings.
- 13 new tests using a fake 5paisa server (41 in total).

## [0.1.0] - 2026-11-14

### Added
- **Claude Code workspace.**
  - `CLAUDE.md` with the hard rules: no orders, code decides, personal use, no automated NSE/BSE access.
  - Slash commands: `/sync`, `/import`, `/portfolio`, `/analyze`, `/sell-review`, `/thesis`, `/report`.
  - The `stock-analysis` skill.
  - Read-only subagents: `filing-reader`, `governance-checker`, `news-summarizer`.
- **Broker MCP config** for Zerodha Kite and INDmoney (`.mcp.json`), with every Kite and 5paisa order or GTT tool denied in `.claude/settings.json`.
- **Deterministic core** (`src/isa`, standard-library Python):
  - SQLite storage with versioned schema.
  - Importers for broker holdings and trades (Kite, INDmoney, 5paisa formats), daily prices, a sector/industry list, and fundamental and shareholding facts.
  - LLM-extracted facts need a page reference and confirmation.
- **Scoring engine:**
  - fundamentals, governance (with vetoes) and valuation blocks
  - an intrinsic-value DCF range
  - technical timing advice
  - labels, confidence and "why"
  - sell triggers: thesis broken, a loss with weakening fundamentals, valuation stretch
- **Tax view:** FIFO lots per demat; STCG 20% (s.196) and LTCG 12.5% above ₹1.25 lakh (s.198) under the Income-tax Act, 2025; long-term dates and wait hints.
- **Portfolio view:** weights, sector exposure, caps (10% / 25%) and broker reconciliation.
- **Self-contained HTML report.**
- **Append-only, hash-chained audit log.**
- **`tools/security_guards.py`**, 28 unit and end-to-end tests, and a CI workflow.

### Not yet included
- The macro, sector and events blocks.
- CAS PDF parsing.
- Loss set-off and grandfathering in the tax view.
- Backtesting.
