# India Stock Analyzer

A **personal-use** tool for analysing and getting recommendations on Indian equities (NSE/BSE), built for a long-term investor. It never does intraday trading.

**Status:** design stage. No feature code yet. Read `docs/FEASIBILITY_AND_DESIGN.md` and `docs/DECISIONS.md`.

## Goal

- Pull portfolio records from **Zerodha Kite, INDmoney and 5paisa**. This uses each broker's official MCP server first, with REST APIs and CAS/CSV imports as fallbacks.
- Score each holding and watchlist stock with an **explainable engine**: macro, sector, fundamentals, governance, valuation, events, and technicals (used for timing only).
- Output BUY / ACCUMULATE / HOLD / TRIM / SELL with a confidence score, a plain-language "why", sell triggers, a portfolio view and tax-aware (STCG/LTCG) suggestions.
- **Never place orders automatically.** The MVP places no orders at all.

## Planned stack

Python 3.12 (uv) · official `mcp` SDK client · PostgreSQL 16 + TimescaleDB · APScheduler · FastAPI (localhost) · Streamlit · Telegram/email alerts · secrets in the macOS Keychain.

## How it will run (planned)

1. `docker compose up db` starts Postgres/TimescaleDB locally.
2. Copy `.env.example` to `.env`. Store broker secrets in the Keychain, not in `.env`.
3. Once a day, log in to each broker (Kite tokens expire at 06:00 and 5paisa tokens at 23:59).
4. The scheduler syncs holdings after market close, refreshes data, recomputes signals and sends a Telegram digest.
5. Review signals in the Streamlit dashboard. Every signal and every decision you make is written to the audit log.

## Boundaries

- Personal use only. Do not share signals: showing recommendations to others can require SEBI RA/IA registration.
- No redistribution of market data.
- Not investment or tax advice.
