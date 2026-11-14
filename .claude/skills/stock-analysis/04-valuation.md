# Valuation

**Multiples now:**
- P/E = price ÷ latest annual EPS
- P/B = price ÷ (equity ÷ shares)
- EV/EBITDA = (price × shares + debt − cash) ÷ EBITDA

Amounts are in INR crore and shares in crore.

**Own history.** The multiple at each past annual filing date, using that day's close, over 10 years. The current multiple's percentile scores as:

| Percentile | Points |
|---|---|
| ≤ 20 | +2 |
| ≤ 40 | +1 |
| ≤ 60 | 0 |
| ≤ 80 | −1 |
| above 80 | −2 |

At least 3 history points are needed.

**Peers.** Stocks with the same industry (or the same sector if no industry is set) that have prices and EPS. P/E below 0.8× the peer median scores +1; above 1.25× scores −1. At least 2 peers are needed. Set the classification with `python3 tools/isa.py security <SYM> --sector ... --industry ...` or `import-securities`.

**PEG** = P/E ÷ EPS CAGR (%). Below 1 scores +1; above 2 scores −1.

**Intrinsic value: a model, not a fact.**
- Method: 2-stage DCF on average free cash flow per share over the last 3 years (CFO − capex).
- Stage-1 growth is the revenue CAGR (5y, else 3y), capped at 20% and floored at 0, for 10 years. Then terminal growth of 5%, at a 12% discount rate.
- Low case: growth × 0.7, discount +1%. High case: growth × 1.2, discount −1%.
- Score: price below low +2; below base +1; up to high 0; up to 1.3× high −1; above that −2.
- Negative free cash flow means no DCF.

All assumptions are in `config/valuation.toml` and appear in the JSON. Always show them with the range.
