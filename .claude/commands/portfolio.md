# /portfolio: score holdings and watchlist

1. Run `python3 tools/isa.py portfolio`. This stores a signal for every stock and writes it to the audit log.
2. Present, using only the JSON:
   - **Summary:** total value, top-5 weight, cap breaches (10% per stock, 25% per sector), reconciliation issues, missing prices or sectors, pending facts.
   - **Holdings table:** symbol, weight, P&L %, **label**, confidence, and one line of "why" built from `why.positive` and `why.negative`.
   - **Triggers** for each holding that has one, using its `detail` text. `thesis_broken` and `loss_with_weakening_fundamentals` force SELL; `valuation_stretch` forces at least TRIM.
   - **Tax waits:** lots in `tax_waits` turn long-term soon. Show `wait_until` and the note.
   - **Watchlist:** label, confidence and timing advice (`timing`) for BUY/ACCUMULATE.
3. For INSUFFICIENT_DATA, say what is missing, from `why.missing` or the low block completeness, and which `/import` would fix it.
4. Confidence is out of 100. In this version the macro, sector and events blocks are not built yet, so confidence tops out at about 70. Say this once.
5. End with: "Not investment or tax advice. Any order is yours to place in the broker app."
6. If the user tells you what they did or decided, record it: `python3 tools/isa.py decision <SYMBOL> <bought|sold|trimmed|added|held|ignored|other> --note "<their words>"`.

Never change a label or add a recommendation the engine did not produce.
