#!/usr/bin/env python3
"""Safety guards. Run: python3 tools/security_guards.py  (exit 1 on any failure)

1. .claude/settings.json denies every broker order/GTT tool and allows none of
   them, and grants no server-wide or shell-wide wildcard.
2. .mcp.json lists only the known broker MCP servers at their official URLs.
3. .gitignore still ignores secrets and local data.
4. No code under src/ or tools/ calls a broker order endpoint: this tool never
   places orders.
5. The 5paisa client's endpoint allowlist holds read-only endpoints only.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ORDER_TOOLS = {
    # Zerodha kite-mcp-server, mcp/post_tools.go
    "mcp__kite__place_order", "mcp__kite__modify_order", "mcp__kite__cancel_order",
    "mcp__kite__place_gtt_order", "mcp__kite__modify_gtt_order", "mcp__kite__delete_gtt_order",
    # 5paisa_MCP, src/tools/*.ts (not used, denied anyway)
    "mcp__fivepaisa__Place_Order", "mcp__fivepaisa__Modify_Order", "mcp__fivepaisa__Cancel_Order",
}
ALLOWED_SERVERS = {
    "indmoney": "https://mcp.indmoney.com/mcp",
    "kite": "https://mcp.kite.trade/mcp",
}
REQUIRED_IGNORES = {".env", ".env.*", "creds.json", "data/*", "*.db", "*.pdf", "*.csv"}
REQUIRED_DENY = {"Read(.env)", "Read(.env.*)", "Read(**/creds.json)",
                 # sites whose terms forbid automated collection, or second-hand aggregators
                 "WebFetch(domain:nseindia.com)", "WebFetch(domain:bseindia.com)",
                 "WebFetch(domain:screener.in)", "WebFetch(domain:tijorifinance.com)",
                 "WebFetch(domain:trendlyne.com)", "WebFetch(domain:moneycontrol.com)",
                 "WebFetch(domain:tickertape.in)"}
ORDER_CODE = re.compile(
    r"(place_order|modify_order|cancel_order|place_gtt|modify_gtt|delete_gtt|PlaceOrderRequest|"
    r"ModifyOrderRequest|CancelOrderRequest|/orders/regular|/gtt/triggers|V1/PlaceOrder|PlaceSMOOrder)",
    re.IGNORECASE,
)
BROAD_ALLOW = re.compile(r"^(Bash|Bash\(\*\)|Bash\(:\*\)|mcp__[A-Za-z0-9]+(__\*)?|WebFetch|\*)$")


def check_settings(errors: list[str]) -> None:
    path = ROOT / ".claude" / "settings.json"
    perms = json.loads(path.read_text()).get("permissions", {})
    allow, deny = set(perms.get("allow", [])), set(perms.get("deny", []))
    for tool in sorted(ORDER_TOOLS - deny):
        errors.append(f"settings.json: order tool not denied: {tool}")
    for tool in sorted(ORDER_TOOLS & allow):
        errors.append(f"settings.json: order tool is allowed: {tool}")
    for entry in sorted(allow):
        if BROAD_ALLOW.match(entry):
            errors.append(f"settings.json: over-broad allow entry: {entry}")
    for entry in sorted(REQUIRED_DENY - deny):
        errors.append(f"settings.json: missing deny entry: {entry}")


def check_mcp(errors: list[str]) -> None:
    servers = json.loads((ROOT / ".mcp.json").read_text()).get("mcpServers", {})
    for name, spec in servers.items():
        if name not in ALLOWED_SERVERS:
            errors.append(f".mcp.json: unexpected MCP server: {name}")
        elif spec.get("url") != ALLOWED_SERVERS[name] or spec.get("type") != "http":
            errors.append(f".mcp.json: {name} must be type http at {ALLOWED_SERVERS[name]}")


def check_gitignore(errors: list[str]) -> None:
    lines = {ln.strip() for ln in (ROOT / ".gitignore").read_text().splitlines()}
    for rule in sorted(REQUIRED_IGNORES - lines):
        errors.append(f".gitignore: missing rule: {rule}")
    for ln in lines:
        if ln.startswith("!") and ln not in ("!.env.example", "!data/.gitkeep"):
            errors.append(f".gitignore: unexpected negation: {ln}")


def check_no_order_code(errors: list[str]) -> None:
    me = Path(__file__).resolve()
    for folder in ("src", "tools"):
        for f in (ROOT / folder).rglob("*.py"):
            if f.resolve() == me:
                continue
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if ORDER_CODE.search(line):
                    errors.append(f"{f.relative_to(ROOT)}:{i}: order-placement reference")


FIVEPAISA_READ_ONLY = {"GetAccessToken", "V3/Holding", "V1/TradeBook", "V3/NetPositionNetWise"}


def check_fivepaisa_allowlist(errors: list[str]) -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from isa.brokers import fivepaisa
    extra = set(fivepaisa.READ_ENDPOINTS.values()) - FIVEPAISA_READ_ONLY
    for path in sorted(extra):
        errors.append(f"5paisa client: endpoint not on the read-only list: {path}")


def main() -> int:
    errors: list[str] = []
    for check in (check_settings, check_mcp, check_gitignore, check_no_order_code, check_fivepaisa_allowlist):
        try:
            check(errors)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{check.__name__}: {exc}")
    if errors:
        print("security guards FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("security guards passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
