# India Stock Analyzer

A **personal-use** tool for analysing and getting recommendations on Indian equities (NSE/BSE), built for a long-term investor. It never does intraday trading.

**Status:** early setup, no feature code yet. Full project documentation will be added as features are built.

## Goal

- Pull portfolio records from **Zerodha Kite and INDmoney** through their official MCP servers, and from **5paisa** through its Xstream REST API (read-only endpoints only). CAS and CSV imports are the fallback.
- Score each holding and watchlist stock with an **explainable engine**: macro, sector, fundamentals, governance, valuation, events, and technicals (used for timing only).
- Output BUY / ACCUMULATE / HOLD / TRIM / SELL with a confidence score, a plain-language "why", sell triggers, a portfolio view and tax-aware (STCG/LTCG) suggestions.
- **Analysis only: the tool never places orders.** You place every order yourself in the broker app.
- No automated access to NSE or BSE websites (NSE terms prohibit it). Exchange files are downloaded by hand into an import folder.

## Planned stack

**Claude Code workspace** (`CLAUDE.md`, slash commands, a skill, read-only subagents, broker MCPs in `.mcp.json`) over a **deterministic Python 3.12 core** (uv) with **SQLite** and a generated **HTML report**. Secrets live in the macOS Keychain. Code decides every label; Claude fetches, extracts and explains.

## How it will run (planned)

1. Open the repo in Claude Code. Sign in to the INDmoney and Kite MCPs once a day (the brokers expire sessions daily).
2. `/sync` pulls holdings, positions and trades through the broker MCPs (read tools only) into `data/isa.db`.
3. Drop manual downloads (CAS, tradebooks, NSE/BSE files, Screener/Tijori exports, annual reports) into `data/imports/` and run `/import`.
4. `/portfolio` runs the scoring engine and shows each holding's label, confidence, "why", sell triggers and tax view. `/analyze <stock>`, `/sell-review`, `/thesis <stock>` and `/report` cover the rest.
5. Every signal and every decision you record is written to the audit log. You place any order yourself in the broker app.
6. Everything runs inside a Claude Code session you start. There are no scheduled runs or push alerts.

## Boundaries

- Personal use only. Do not share signals: showing recommendations to others can require SEBI RA/IA registration.
- No redistribution of market data.
- Not investment or tax advice.
