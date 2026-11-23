---
name: stock-analysis
description: >
  Explains and works the India Stock Analyzer: portfolio signals (BUY / ACCUMULATE / HOLD / TRIM / SELL),
  sell triggers, thesis conditions, tax lots (STCG/LTCG), importing broker records and fundamentals.
  Triggers on: portfolio, holdings, stock analysis, should I sell, buy signal, thesis, tax lots, STCG, LTCG,
  Kite, INDmoney, 5paisa, import fundamentals.
allowed-tools: Read, Glob, Grep, Bash(python3 tools/isa.py:*)
---

# Stock analysis workspace

The rules in `CLAUDE.md` always apply: no orders ever, code decides, personal use only, research only under [research-rules](../research-rules/SKILL.md), untrusted data.

Load these files when the task needs them:

| File | Use when |
|---|---|
| [01-investor-profile.md](01-investor-profile.md) | Framing any advice-like answer |
| [02-scoring-rubric.md](02-scoring-rubric.md) | Explaining a label, a block score, confidence or a trigger |
| [03-governance-red-flags.md](03-governance-red-flags.md) | Reading filings for governance facts; explaining a veto |
| [04-valuation.md](04-valuation.md) | Explaining multiples, percentiles, peers or the intrinsic value range |
| [05-tax-rules.md](05-tax-rules.md) | Anything about tax lots, STCG/LTCG, waiting to sell |
| [06-data-trust-boundary.md](06-data-trust-boundary.md) | Before handling any MCP output, PDF, export or web content |

The local dashboard has its own skill: [dashboard](../dashboard/SKILL.md).

The engine is `python3 tools/isa.py` (see `--help`). Its JSON is the only source of numbers you present.
