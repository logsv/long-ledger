# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

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
