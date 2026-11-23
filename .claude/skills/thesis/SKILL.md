---
name: thesis
description: Write or review the checkable thesis conditions for one stock.
argument-hint: "<SYMBOL>"
arguments: symbol
disable-model-invocation: true
allowed-tools: Bash(python3 tools/isa.py:*)
---

# /thesis <SYMBOL>: write or review checkable thesis conditions

A thesis is a short list of conditions the engine can check, for example: "revenue 3y CAGR stays above 12%", "promoter pledge stays at 0", "ROCE above 18%". When any condition fails, the stock gets a `thesis_broken` trigger and is labelled SELL for review.

1. Run `python3 tools/isa.py thesis list $symbol` and `python3 tools/isa.py analyze $symbol --no-record`.
2. Show the current conditions, with the current value and status of each (`holds`, `broken` or `unknown`).
3. If the user wants to add conditions, turn their words into `metric op threshold` using metric keys that appear in the analyze evidence (`key`) or in `python3 tools/isa.py metrics`. Examples:
   - `revenue_cagr_3y >= 12`
   - `roce >= 18`
   - `promoter_pledge_pct <= 0`
   - `debt_to_equity <= 0.5`
   - `promoter_change_1y >= -2`

   Confirm the exact conditions with the user, then run `python3 tools/isa.py thesis add <SYMBOL> <metric> '<op>' <threshold> --note "<their reason>"`. Quote the operator.
4. To drop one, run `python3 tools/isa.py thesis retire --id <N>`, only when the user asks.
5. Growth and percentage metrics are plain numbers: 12 means 12%.
