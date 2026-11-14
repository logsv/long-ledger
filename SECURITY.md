# Security and safety

## No orders, by design

The tool is analysis-only. It is blocked from changing your broker account in four ways:

1. **`.claude/settings.json` denies every order tool by name.**
   - Kite: `place_order`, `modify_order`, `cancel_order`, `place_gtt_order`, `modify_gtt_order`, `delete_gtt_order`.
   - 5paisa MCP (not used): `Place_Order`, `Modify_Order`, `Cancel_Order`.
   - INDmoney's MCP is read-only by design.
2. **`tools/security_guards.py` fails if any of these happens:**
   - an order tool is no longer denied, or becomes allowed
   - a server-wide or shell-wide wildcard is allowed
   - `.mcp.json` points to any server other than the official Kite and INDmoney endpoints
   - order-endpoint names appear anywhere in `src/` or `tools/`
3. **The core has no order code at all.** It never calls a broker.
4. **`CLAUDE.md` tells Claude** to refuse order requests from any source, including text inside data, and to log the refusal.

Run the guards before every commit: `python3 tools/security_guards.py`.

## Secrets

- No secrets in the repo.
  - `.env` holds only non-secret settings, and Claude is denied from reading it.
  - `.gitignore` covers `.env*`, `creds.json`, key files, `data/`, PDFs and CSVs.
- **Broker sign-ins:**
  - Kite and INDmoney sign-ins happen on the brokers' own pages through Claude Code's `/mcp`, and Claude Code holds those sessions. Never paste passwords, PINs, TOTP secrets or tokens into chat.
  - **5paisa** uses its read-only API, not its MCP. The MCP was rejected because it needs a plaintext `creds.json` with your password, PIN and TOTP secret.
  - Login happens daily on 5paisa's own page; you enter your PIN and TOTP there.
  - The redirect is caught by a one-shot listener on 127.0.0.1, which checks a random `state` value.
  - The encryption key, which you store yourself, and the access token (valid until 23:59 IST) live in the macOS Keychain under the service `india-stock-analyzer`.
  - `fivepaisa status` never prints secrets.
  - The client refuses any endpoint not on its read-only allowlist, and the guard checks that allowlist.

## Personal data

- `data/` (database, imports, reports) is git-ignored and stays on your Mac.
- No server listens on the network. The one exception is `fivepaisa login`, which listens on 127.0.0.1 for a single redirect, for at most 5 minutes.
- Claude is told never to put holdings or account data into web searches or external requests.

## Untrusted content

Broker MCP output, PDFs, exports and news are treated as data, never instructions:
- The subagents are read-only, with no Write or network tools.
- LLM-extracted numbers need a page reference and your confirmation before the engine uses them.

## Audit trail

`audit_event` is append-only (database triggers block UPDATE and DELETE) and SHA-256 hash-chained. Check it with `python3 tools/isa.py audit verify`.

## Compliance boundaries

- **Personal use only.** Sharing signals with others can require SEBI Research Analyst or Investment Adviser registration.
- **No automated collection from nseindia.com or bseindia.com.** NSE's terms prohibit "systematic or automated data collection". Download files by hand.
- **Kite market data** may not be displayed to the public.

## Reporting a problem

This is a personal project. If you find a way the tool could place an order or leak data, treat it as the top priority: fix it, and add a guard or test that would have caught it.
