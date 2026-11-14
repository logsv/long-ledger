# Governance red flags

**Vetoes.** Any of these blocks BUY/ACCUMULATE; the label falls back to HOLD:
- promoter pledge above 25% of promoter holding
- pledge up 5 or more points in a year
- a qualified or adverse audit opinion
- the statutory auditor resigning within the last 2 years

**Negatives:**
- related-party transactions above 10% of revenue (−1), or above 20% (−2)
- share count growing more than 5% a year (−1), or more than 10% (−2)
- promoter holding falling 3 or more points in a year (−1), or 8 or more points (−2)
- FII+DII holding down 2 or more points

**What to extract from filings** (metric names for `import-facts`):

| Metric | Value | Where to find it |
|---|---|---|
| `auditor_qualified` | 1 or 0 | Independent auditor's report, "Opinion" section; the year's period_end |
| `auditor_resigned` | 1 | Stock exchange disclosure; the resignation date as period_end |
| `rpt_pct_revenue` | % | Related-party transactions note, total RPT value ÷ revenue × 100 |
| `promoter_pct`, `promoter_pledge_pct`, `fii_pct`, `dii_pct`, `mf_pct` | % | Quarterly shareholding pattern; quarter end as period_end |

Always give `source_ref` as `<file name> p.<page>`, and the filing date as `published_at`.
