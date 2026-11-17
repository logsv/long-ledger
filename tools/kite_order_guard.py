#!/usr/bin/env python3
"""PreToolUse hook for the Kite MCP `orders` tool: read modes only.

Kite's MCP server folded reading and changing orders into one tool that picks
the action with a `mode` argument, so a settings.json deny entry can no longer
separate the two. This hook reads the tool call from stdin and blocks every
mode that is not on the read-only list (exit 2 blocks the call).
"""

from __future__ import annotations

import json
import sys

READ_MODES = {"list", "history", "trades", "all_trades"}


def main() -> int:
    try:
        call = json.load(sys.stdin)
        mode = (call.get("tool_input") or {}).get("mode")
    except (json.JSONDecodeError, AttributeError):
        mode = None
    if mode in READ_MODES:
        return 0
    print(f"blocked: Kite orders mode {mode!r} is not read-only. Allowed modes: "
          f"{', '.join(sorted(READ_MODES))}. The user acts in the broker app.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
