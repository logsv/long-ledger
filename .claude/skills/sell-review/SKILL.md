---
name: sell-review
description: List holdings with TRIM/SELL labels or sell triggers, with lot-by-lot tax impact and wait dates. Use when the user asks what to sell or trim.
allowed-tools: Bash(python3 tools/isa.py:*)
---

# /sell-review: holdings that may need selling or trimming

1. Run `python3 tools/isa.py portfolio` and `python3 tools/isa.py tax`.
2. List the holdings whose label is TRIM or SELL, or that have any trigger other than `thesis_unchecked`. For each, show:
   - The label, confidence and trigger `detail`.
   - The evidence behind it: the negative `why` lines and any veto.
   - **Tax impact** from the tax JSON, lot by lot: term, unrealised gain, estimated tax if sold today, and any `wait_until` date.
     - If a lot turns long-term within the window and no `thesis_broken` trigger fired, point out the wait date and the estimated saving the engine reports.
     - A thesis break is a reason not to wait. Say so.
   - Remaining LTCG exemption this financial year (`ltcg_exemption_remaining`).
3. Also list `loss_watch` holdings: down 20% or more, but fundamentals have not weakened. That is not a sell signal.
4. Be honest about the limits: loss set-off, grandfathering and STT are not modelled, so figures are gross estimates.
5. Ask what the user decided and record it with `python3 tools/isa.py decision ...`. Never place or offer an order.
6. End with "Not investment or tax advice."
