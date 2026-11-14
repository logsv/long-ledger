# /report: HTML portfolio report

1. Run `python3 tools/isa.py report`, or `python3 tools/isa.py report --out <path>` if `$ARGUMENTS` gives a path.
2. The report is a single self-contained HTML file. By default it goes to `data/reports/portfolio-<date>.html`, which git ignores because it holds personal data. Tell the user the path.
3. Summarise in one or two lines: number of holdings, labels count, and anything in "Needs attention".
4. Do not publish, upload or share the report anywhere. It is for the user only (personal use; SEBI RA/IA boundary).
