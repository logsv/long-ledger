# Investor profile

- Long-term investor in Indian listed equities (NSE/BSE). Never trades intraday or same-day.
- Sells when the analysis says so:
  - to book profit when valuation is stretched
  - to cut a loss when fundamentals are also weakening
  - to exit when the thesis is broken
- Every BUY/SELL must rest on company and market analysis, never on price action alone. Technicals only shape *how* to act: stagger an entry, or enter normally.
- Brokers: Zerodha Kite (MCP), INDmoney (MCP), 5paisa (read-only API via `tools/isa.py fivepaisa`).
- User settings (`config/thresholds.toml`):
  - loss trigger at 20% plus weakening fundamentals
  - caps of 10% per stock and 25% per sector
- Universe: current holdings plus the watchlist.
- Personal use only. The signals are not shared with anyone.
