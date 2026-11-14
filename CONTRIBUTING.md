# Contributing

## Setup

- Python 3.12 or newer. The core uses only the standard library: `sqlite3`, `tomllib`, `argparse`.
- No install step. `tools/isa.py` adds `src/` to the import path.

## Before every commit

```bash
python3 -m unittest discover -s tests
python3 tools/security_guards.py
```

Both must pass. CI (`.github/workflows/ci.yml`) runs the same two commands.

## Rules for changes

1. **No order placement code, ever.** Not for any broker, not behind a flag. The guard scans for order-endpoint names.
2. **Determinism.** Engine code must be a pure function of stored data and `config/`. No network calls, no LLM calls, no current-time reads inside scoring. The evaluation date is passed in.
3. **Point-in-time.** Read facts only through `engine.base.Data`, which hides anything published after the evaluation date and any unconfirmed LLM fact.
4. **Config, not constants.** Weights, thresholds, valuation assumptions and tax rates go in `config/*.toml`. A tax-rate change must cite an official source URL.
5. **Explainability.** Every scored input must produce an `Evidence` line with plain-language text and a stable `key`, which thesis conditions use.
6. **Tests.** Add a test for every new rule, trigger or importer alias. Use synthetic data only (`tests/fixtures.py`). Never commit real portfolio data.
7. **Untrusted input.** Importers validate types and units, and skip bad rows with a reason. They never execute or interpret text from data.
8. **Workspace prompts.** Changes to `CLAUDE.md`, `.claude/commands`, `.claude/skills` or `.claude/agents` must keep the hard rules: no orders, code decides, personal use, no automated NSE/BSE access, untrusted data.

## Commit messages

Use Conventional Commits: `feat(engine): ...`, `fix(tax): ...`, `docs: ...`, `chore: ...`. Update `CHANGELOG.md` for user-visible changes.
