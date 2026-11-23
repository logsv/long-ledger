---
name: sell-review
description: List holdings with TRIM/SELL labels or sell triggers, with lot-by-lot tax impact and wait dates. Use when the user asks what to sell or trim.
allowed-tools: Bash(python3 tools/isa.py:*)
---

# /sell-review: holdings that may need selling or trimming

A sell decision weighs four things together; no single number should trigger it. This command lays out the evidence for each holding worth a review, plus the tax cost. It never places or offers an order.

`$ARGUMENTS`: empty for every holding worth a review, or one or more symbols.

1. Run `python3 tools/isa.py sell-check [SYMBOLS] --history`. Without symbols it returns held stocks with label TRIM or SELL, a sell trigger (other than `thesis_unchecked` and `loss_watch`), or two or more concerns. Also run `python3 tools/isa.py tax` for lot detail.
2. For each stock, using only the JSON:
   - **Label and confidence** (from the engine) and any trigger `detail`.
   - **The four checks** as a short table, each with its status (✓ OK, ! Watch, ✗ Concern, ? No data), `headline` and up to three `lines`:
     1. **Fundamentals:** is the business getting worse? (score now vs a year ago; `score_history` shows the last 12 quarters)
     2. **Trend:** is the market telling me something? (200-day average, relative strength vs NIFTY 500, drawdown)
     3. **Future:** is the reason I bought still true? (thesis conditions; recent news headlines)
     4. **Team and governance:** can I trust the people running it? (pledge, promoter change, auditor, related parties, dilution, vetoes)
   - The `summary.verdict` line.
   - **Tax:** gain, tax if sold now, and `next_long_term`. If a lot turns long-term soon and there is no thesis break, point out the date and the saving. A thesis break is a reason not to wait; say so.
   - Remaining LTCG exemption this financial year (`ltcg_exemption_remaining`).
3. Where **Future is "No data"**, offer to write a thesis with `/thesis <SYMBOL>`: 2-3 measurable conditions from the stock's own numbers (for example "ROCE stays above 15%", "pledge stays below 5%"). Without one, the most important check can't run.
4. Also list `loss_watch` holdings: down 20% or more, but fundamentals have not weakened. That is not a sell signal.
5. Be honest about the limits: loss set-off, grandfathering and STT are not modelled, so tax figures are gross estimates. The four checks are rules on the engine's numbers and do not change the label.
6. Mention that the dashboard shows the same check with charts (click the stock in Holdings), and the HTML report has a Sell check table.
7. Ask what the user decided and record it with `python3 tools/isa.py decision <SYMBOL> <sold|trimmed|held|...> --note "<their words>"`. Never place or offer an order.
8. End with "Not investment or tax advice."
