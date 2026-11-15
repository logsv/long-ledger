# /portfolio: score holdings and watchlist

1. Run `python3 tools/isa.py portfolio`. This stores a signal for every stock and writes it to the audit log.
2. Present, using only the JSON:
   - **Market:** the `market.regime` line, index trend and India VIX, breadth, and the sector-index leaders and laggards.
   - **Summary:** total value, top-5 weight, allocation by asset class and market cap, and cap breaches. The caps are: 10% per stock; gold + silver; small caps; 25% per sector when sectors exist. Also reconciliation issues, unclassified holdings, and pending facts.
   - **Holdings table:** symbol, weight, P&L %, **label**, confidence, and one line of "why" built from `why.positive` and `why.negative`.
   - **Triggers** for each holding that has one, using its `detail` text. `thesis_broken` and `loss_with_weakening_fundamentals` force SELL; `valuation_stretch` forces at least TRIM.
   - **Tax waits:** lots in `tax_waits` turn long-term soon. Show `wait_until` and the note.
   - **Watchlist:** label, confidence and timing advice (`timing`) for BUY/ACCUMULATE.
3. **Monitoring flags** (`flags`): `weak_trend`, `deep_drawdown`, `volume_spike`, `loss_from_cost`. List them per stock and call them **review prompts, not sell signals**.
   - `ETF` holdings get no company label. Show their timing and allocation only.
4. For INSUFFICIENT_DATA, say what is missing, from `why.missing` or the low block completeness, and which `/import` would fix it.
5. Confidence is out of 100. The sector and events blocks are not built yet, so confidence tops out at about 80 (70 without index data). Say this once. With broker data only, there is no company data, so stocks stay INSUFFICIENT_DATA. In that case present the market, allocation and flags as the main output. Don't list 'missing' lines per stock. Say once that company data is missing, then show flagged holdings first.
6. End with: "Not investment or tax advice. Any order is yours to place in the broker app."
7. If the user tells you what they did or decided, record it: `python3 tools/isa.py decision <SYMBOL> <bought|sold|trimmed|added|held|ignored|other> --note "<their words>"`.

Never change a label or add a recommendation the engine did not produce.
