#!/usr/bin/env python3
"""Entry point for the isa core CLI. See `python3 tools/isa.py --help`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from isa.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
