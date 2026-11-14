# /analyze <SYMBOL>: full breakdown for one stock

1. Run `python3 tools/isa.py analyze $ARGUMENTS`. If the stock is new, suggest `python3 tools/isa.py watch add <SYMBOL>`, then `/sync` for prices and `/import` for fundamentals.
2. Present from the JSON only:
   - **Label, confidence and composite**, plus the confidence parts (coverage, completeness, agreement, freshness).
   - **Each block** (fundamentals, governance, valuation): its score, completeness, and every evidence line (`text`). Mark lines with `points: null` as informational.
   - **Governance vetoes**, if any. They block BUY/ACCUMULATE.
   - **Valuation:** current multiples and the intrinsic value range with **all its assumptions** (growth used, discount rate, terminal growth, years). Say plainly that it is a model, not a fact.
   - **Timing** (technicals): observations and advice. Timing never changes the label.
   - **Triggers and thesis status**, if the stock is held.
   - **Tax lots** for this stock: term today, days to long-term, estimated tax if sold.
3. Say which inputs are missing and how to add them.
4. End with "Not investment or tax advice."
