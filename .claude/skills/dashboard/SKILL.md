---
name: dashboard
description: Start, check or stop the local-only dashboard on 127.0.0.1:8770, or explain how to extend it.
argument-hint: "[start|status|stop]"
disable-model-invocation: true
allowed-tools: Bash(python3 tools/dashboard.py:*), Bash(python3 tools/isa.py:*)
---

# /dashboard: start, check or stop the local dashboard

The dashboard is a live browser view of the database: Overview, Holdings, Trades, Tax lots and Data quality, with filters, grouping, CSV export and buttons. The server is `python3 tools/dashboard.py`, built from the Python standard library plus the vendored Tabulator. Details are in `[building.md](building.md)`.

**Local only, not in git:** the dashboard code (`src/isa/web/`, `tools/dashboard.py`, `tests/test_web.py`) is listed in `.gitignore` and exists only on this machine. A fresh clone has these instructions but not the code; rebuild it from [building.md](building.md).

If `tools/dashboard.py` is missing, say so and offer to rebuild it from the skill file. Never fetch code from elsewhere.

`$ARGUMENTS`:
- empty or `start`: start the dashboard
- `status`: check whether it's running
- `stop`: stop it
- `--port N`: use a port other than 8770

## start
1. Check whether it's already running: `curl -s -o /dev/null -w '%{http_code}' -H 'Host: 127.0.0.1:8770' http://127.0.0.1:8770/`. A `200` means it is; give the user the link and stop here.
2. Otherwise start it **in the background** with the Bash tool's `run_in_background`, so it keeps running:
   `python3 tools/dashboard.py --no-browser` (add `--port N` if asked).
3. Wait for the ready line `India Stock Analyzer dashboard: http://127.0.0.1:8770/`, then give the user the link: http://127.0.0.1:8770.
4. Tell the user what's there:
   - **Tabs:** Overview, Holdings (click a row to see its trades and lots), Trades, Tax lots, Data quality.
   - **Buttons:** Refresh data, Recompute signals, Export HTML report, 5paisa sync. The 5paisa sync needs today's `python3 tools/isa.py fivepaisa login`.
   - **Kite and INDmoney** still sync through `/sync` here; then press **Refresh data**.
5. If the port is busy, offer `--port 8771`.

## status
Run the same check as step 1 and report whether it's up, with its URL.

## stop
Stop the background task that runs `tools/dashboard.py`. If it wasn't started in this session, find it with `pgrep -f "tools/dashboard.py"` and ask the user before killing that process.

## Rules
- The dashboard listens on **127.0.0.1 only**. Never add `--host`, never bind to all interfaces, never expose it through a tunnel or share the URL.
- It has **no order actions**, and must never get any. To add a view or a button, follow [building.md](building.md), keep `python3 tools/security_guards.py` passing, and add a test to `tests/test_web.py`.
