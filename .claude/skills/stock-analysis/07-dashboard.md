# Local dashboard

**What it is:** a standard-library HTTP server with a static page that uses Tabulator 6.3.1 (MIT), stored locally. There's no Node.js at run time and no CDN.

**Local only, not in git:** `src/isa/web/`, `tools/dashboard.py` and `tests/test_web.py` are git-ignored and exist only on this machine.
- `tools/security_guards.py` still scans `src/isa/web` for order-endpoint names whenever the folder is present.
- To rebuild on a new machine, follow this file. Tabulator comes from bun (see "Updating Tabulator").
- The server registers its own `ui_action` audit event type at import.
- The launcher is `tools/dashboard.py` (argparse `--port` and `--no-browser`; it calls `isa.web.server.serve`).

**How to run it:** use `/dashboard`, or `python3 tools/dashboard.py [--port N] [--no-browser]`. The URL is http://127.0.0.1:8770.

## Files

| File | Role |
|---|---|
| `src/isa/web/server.py` | `Dashboard` (cached `service.run`, read-only database connections), `make_handler` (routes and security checks), `serve()`. The constants `HOST = "127.0.0.1"` and `ACTIONS` live here |
| `src/isa/web/api.py` | JSON views: `overview`, `holdings`, `trades`, `lots`, `quality`. They return flat rows shaped for Tabulator. Holdings rows carry the scorecard flattened as `m_<key>` (value), `t_<key>` (tone), `x_<key>` (text), plus `ret_yr` and the full `card` |
| `src/isa/web/static/index.html` | Tabs, toolbars and buttons. `{{TOKEN}}` is replaced at serve time |
| `src/isa/web/static/app.js` | Table definitions, the Position / Business / Valuation column views (`VIEWS`), the scorecard panel (`renderScorecard`), toolbar filters, grouping, CSV download, action calls |
| `src/isa/web/static/app.css` | Light and dark theme. Light uses `tabulator.min.css`, dark uses `tabulator_midnight.min.css` |
| `src/isa/web/static/vendor/tabulator/` | `tabulator.min.js`, the CSS files, `LICENSE`, and `VERSION` with SHA-256 checksums |
| `tests/test_web.py` | Server tests on a temporary database |

## Routes

| Route | What it does |
|---|---|
| `GET /` | The page, with the per-run token in `<meta name="isa-token">` |
| `GET /static/...` | Files under `web/static` only; path traversal is refused |
| `GET /api/{overview,holdings,trades,lots,quality}` | JSON from a read-only database connection. Engine results are cached until refresh |
| `GET /api/charts`, `/api/stock/<SYM>`, `/api/sellcheck/<SYM>` | Chart HTML built by `src/isa/charts.py` (plain SVG, every text value escaped) and the sell check. Symbols must match `[A-Z0-9&_.-]` and be a holding or watchlist stock |
| `GET /static/charts.css` | `charts.CHART_CSS`, the stylesheet shared with the HTML report |
| `POST /api/action/{refresh,recompute,report,fivepaisa_sync}` | Needs the `X-ISA-Token` header and a same-origin request. Each action is written to the audit log as `ui_action` |

## Security rules (never weaken)
- Listen on `127.0.0.1` only. Refuse any other `Host` header (code 421).
- Data views use `mode=ro` database connections. Only actions write.
- Actions need the per-run token, and the `Origin` must be `http://127.0.0.1:<port>` or `http://localhost:<port>`.
- The CSP allows scripts only from this server (`script-src 'self'`): no inline scripts, no CDN.
- **No order, GTT or alert actions, ever.** `tools/security_guards.py` checks three things:
  - `HOST` is `127.0.0.1`
  - `ACTIONS` contains only the allowed set
  - no `0.0.0.0` or order-endpoint names appear in `src/isa/web`

## Extending

**New table or view:**
1. Add a function to `api.py` that returns a list of flat dicts.
2. Route it in `Dashboard.view`.
3. Add a tab and a toolbar in `index.html`.
4. Add a `makeTable(...)` call with header filters in `app.js`, and load it in `loadAll`.
5. Add a test in `tests/test_web.py`.

**New button:**
1. Add the name to `ACTIONS` in `server.py` and to `DASHBOARD_ACTIONS` in `tools/security_guards.py`.
2. Implement it in `Dashboard.action`; it must call existing core functions only.
3. Add a `data-action` button in `index.html`, and a test.

Buttons may only refresh, recompute, export or run read-only syncs. Kite and INDmoney MCP syncs can't run from the server, because MCP lives in Claude Code: keep those in `/sync`.

**Updating Tabulator:**
1. Download with `bun add tabulator-tables@<version> --ignore-scripts` in a scratch folder.
2. Copy the `dist/js/tabulator.min.js` and `dist/css/*` files you use, plus `LICENSE`.
3. Update `VERSION` with new checksums.
4. Run the tests and click through every tab.

## Checklist after any change
- `python3 -m unittest discover -s tests` and `python3 tools/security_guards.py` both pass.
- Open the dashboard and click through all five tabs: no console errors, filters and grouping work, buttons show a toast.
