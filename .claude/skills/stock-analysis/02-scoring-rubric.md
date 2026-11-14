# Scoring rubric (what the engine does)

**Blocks.** Each block scores from −2 to +2. A block's score is the mean of its scored evidence lines. Its completeness is the share of expected inputs that were present.

| Block | Weight | Status |
|---|---|---|
| Fundamentals (c) | 0.30 | built |
| Governance (d) | 0.20 | built; a red flag vetoes BUY/ACCUMULATE |
| Valuation (e) | 0.20 | built |
| Macro (a), Sector (b), Events (g) | 0.10 each | not built yet |
| Technicals (f) | 0 | timing advice only |

**Composite.** The weighted mean over blocks with at least 30% completeness. If no block reaches that, the label is INSUFFICIENT_DATA.

**Label.**

| Composite | Label |
|---|---|
| ≥ 1.0 | BUY |
| ≥ 0.4 | ACCUMULATE |
| > −0.4 | HOLD |
| > −1.0 | TRIM |
| otherwise | SELL |

**Confidence (0–100)** = coverage × completeness × agreement × freshness.
- **Coverage:** the share of all block weight that had data. It is at most 0.7 until the Phase 2 blocks exist.
- **Agreement:** the share of blocks pointing the same way as the composite.
- **Freshness:** 0.7 if there is no filing in about 15 months; 0.8 if the price is more than 7 days old.

**Sell triggers (held stocks only):**

| Trigger | Effect |
|---|---|
| `thesis_broken` | A user-written condition failed. Label becomes SELL. |
| `loss_with_weakening_fundamentals` | Down ≥ 20% AND the fundamentals score fell by ≥ 1.0 against about 182 days earlier. Label becomes SELL. |
| `valuation_stretch` | Price more than 30% above the upper intrinsic value. Label becomes at least TRIM. |
| `loss_watch` | Down ≥ 20% but fundamentals are intact. Information only; a loss alone never sells. |
| `thesis_unchecked` | A thesis metric has no data yet. |

**Fundamentals evidence keys** (usable in thesis conditions; percentages are plain numbers):
- Growth: `revenue_cagr_5y`, `revenue_cagr_3y`, `pat_cagr_*`, `eps_cagr_*`
- Returns: `roe`, `roce`, `ebitda_margin`
- Balance sheet: `debt_to_equity`, `interest_coverage`
- Cash: `cash_conversion`, `fcf_positive_years`, `working_capital_days`, `dividend_payout`

**Governance keys:** `promoter_pledge_pct`, `promoter_change_1y`, `auditor_qualified`, `auditor_resigned`, `rpt_pct_revenue`, `share_dilution_cagr`, `institutional_change_1y`.

**Valuation keys:** `pe_percentile`, `pb_percentile`, `ev_ebitda_percentile`, `pe_vs_peers`, `peg`, `price_vs_intrinsic`.
