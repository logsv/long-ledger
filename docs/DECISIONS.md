# Decision Log

Each entry gives the choice, why it was made, and when to revisit it. The evidence is in `FEASIBILITY_AND_DESIGN.md` (section references below). Status of every decision: **proposed**, awaiting user approval.

| ID | Decision | Reason | Revisit if |
|---|---|---|---|
| D-01 | Standalone repo at `~/Documents/india-stock-analyzer`, personal use only | Unrelated to other projects. Personal use stays outside SEBI IA/RA registration triggers (§4.1). | The user wants to share signals |
| D-02 | **MCP-first broker records** (user direction 2026-11-14: "GO with MCP to fetch records"). REST and file imports are fallbacks. | All three brokers ship official MCP servers. INDmoney has no public REST API, so MCP is its only route (§1). One generic MCP client covers all three. | A hosted MCP blocks non-Claude OAuth clients. Then use Claude-mediated sync (§1.4). |
| D-03 | Integration order: INDmoney MCP → Kite MCP (Kite Connect REST if needed) → 5paisa REST (read-only) → CAS import | INDmoney's MCP is read-only by design. Kite is the best documented. The 5paisa MCP can place orders. CAS reconciles quantities across all demats. | Hosted Kite MCP reliability issues |
| D-04 | **No automatic orders. The MVP places no orders at all.** Any later order needs explicit per-order confirmation. | User requirement. Kite terms say the "APIs are not meant for placing fully automated trades". Avoids the SEBI algo registration and black-box RA rules (§4.2). | Never automate. Confirm-to-place is the most this will ever allow. |
| D-05 | Do not use the 5paisa local MCP in the MVP | It exposes order placement, and its setup stores the TOTP secret and PIN in a plain `creds.json` (§1.2) | 5paisa adds a read-only mode or OS-keystore secret handling |
| D-06 | Read-only tool **allowlist** in the MCP client; order tools refused in code and logged | Defence in depth, even when a server claims to be read-only. The hosted Kite MCP's exposed tools conflict across sources (§1.1). | — |
| D-07 | Signals are a weighted factor score with evidence; technicals are timing only, with zero weight on the label | Requirement that signals rest on market and company analysis, not price action. Keeps every label explainable (§3). | Backtest shows the weights need recalibrating |
| D-08 | Governance red flags act as a **veto** on BUY/ACCUMULATE, not just a score | Pledges, qualified audits and auditor resignations are asymmetric risks for long-term holders | — |
| D-09 | Tax rates live in `config/` with a source URL and effective date, never hard-coded | Rates changed on 23 Jul 2024. The Income-tax Act 2025 is in force from 1 Apr 2026, and its section mapping is unverified (§3.5). | Each Union Budget |
| D-10 | FIFO lots per demat for tax | The Income Tax Department says demat holding periods use FIFO (§3.5) | — |
| D-11 | Python 3.12 + Postgres 16/TimescaleDB + APScheduler + FastAPI + Streamlit + Telegram | Official broker SDKs and the MCP SDK are available in Python, which is the user's primary language. One database for relational and time-series data. Fastest route to a usable single-user UI (§5.1). | UI outgrows Streamlit (then Next.js) |
| D-12 | Secrets in the macOS Keychain; tokens encrypted at rest; `.env` holds no secrets | No secrets in the repo; tokens expire daily but are still sensitive (§4.4) | Moving to a server (then a secrets manager) |
| D-13 | Append-only audit log of signals, syncs, decisions and order requests, kept for 5+ years | Explainability and self-review. Kite terms ask for logs "for at least 5 years". | — |
| D-14 | Do not scrape Screener, Tijori or broker websites | Their terms limit use to personal, non-commercial use and forbid copying or mirroring; Kite forbids crawlers (§2, §4.3) | A licensed export or API is available |
| D-15 | Fundamentals: exchange filings plus manual personal exports in the MVP; decide on a paid vendor before Phase 2 | No free, licence-clear fundamentals API was verified (§2) | User approves a budget (Q4) |
| D-16 | Backtests use `published_at` for fundamentals, survivorship-free universes and out-of-sample reporting | Avoids look-ahead and survivorship bias (§3.6) | — |
| D-17 | Localhost-only service, no multi-user accounts, no public URLs | Data redistribution limits (Kite: no public display) and the IA/RA boundary | — |
