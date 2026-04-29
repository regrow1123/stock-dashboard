# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Self-hosted single-user portfolio dashboard for Korean + US equities. Ingests trades/dividends via a Telegram bot powered by an LLM agent that uses MCP tools to query and mutate the DB, fetches prices from Yahoo Finance (yfinance), and serves a responsive web UI. Runs as a single Docker Compose service behind Tailscale / Cloudflare Tunnel.

## Architecture

**Single FastAPI process** (`app/main.py:create_app`) that composes three concerns:

1. **HTTP API + web views** — `app/api.py` (JSON at `/api/*`), `app/views.py` (Jinja pages `/` and `/accounts/{id}`), Jinja templates in `web/templates/`, vanilla JS + Chart.js in `web/static/`.
2. **Telegram ingestion** — `app/telegram.py` supports two modes controlled by `TG_POLLING` (default `true`):
   - **Polling** (`poll_updates_job`, 30s APScheduler): calls `getUpdates`, advances offset stored in `meta.tg_offset` — works behind NAT, no HTTPS needed.
   - **Webhook** (`POST /telegram/webhook`, secret-token header): for public HTTPS deployments (Cloudflare Tunnel).
   Both paths call `handle_message(db, msg)` which validates chat id, appends to a sliding-window context, and invokes `app/agent.py:run_agent`. The reply text from the agent is sent back to Telegram.
3. **Background jobs** — `app/scheduler.py` (APScheduler, TZ Asia/Seoul): 15-min live-price refresh, 23:30 daily snapshot recompute (last 7 days), 23:45 benchmark backfill, 30-s Telegram polling, 07:00 KRX listings cache refresh.

**Agent** (`app/agent.py`): builds a system prompt + sliding-window conversation history + the user's message, then shells out to `claude -p --mcp-config mcp.json --allowedTools <11 tools> -p <prompt>`. The CLI launches `python -m app.mcp_server` as a stdio MCP child; the LLM calls tools like `t_search_ticker_kr`, `t_record_trade`, `t_list_holdings` to do its work. The CLI returns the LLM's final text, which is the Telegram reply. **Flag order matters** — `--allowedTools <tools...>` is variadic and would consume the prompt; put `-p <prompt>` last.

**MCP tools** (`app/mcp_server.py`): 7 read-only (`t_list_accounts`, `t_list_holdings`, `t_recent_trades`, `t_recent_dividends`, `t_search_ticker_kr`, `t_verify_ticker_us`, `t_lookup_ticker`) + 4 write (`t_record_trade`, `t_record_dividend`, `t_cancel_trade`, `t_register_instrument`). Each write tool also handles its downstream effects (price backfill for new tickers, snapshot recompute, instrument upsert).

**KRX listings cache** (`app/krx_listings.py`): in-memory `KrxCache` populated from `FinanceDataReader.StockListing("KRX")`. Persisted as `data/krx_cache.pkl`; lazy-hydrated on first `get_cache()` call (so each short-lived MCP subprocess gets it cheaply); refreshed daily at 07:00 by APScheduler. Maps Korean name → ticker with KOSPI `.KS`/KOSDAQ `.KQ` suffixes; substring fallback when no exact match.

**Snapshot model** (`app/snapshots.py:recompute_snapshots`): snapshots are *derived*, never authoritative. `quantity(D, account, ticker) = seed_holdings + Σ trades(executed_at ≤ D)`. Each recompute **deletes then reinserts** snapshot rows in the date range so late-reported trades back-fill history correctly. Called after every trade insertion with `from_date=executed_at` and by the daily job with `from_date=today-7d`.

**Currency isolation**: accounts have their own currency; totals are summed *within* each currency, never across. Benchmark for each account is picked by currency (`BENCHMARK_FOR_CURRENCY`: KRW → `^KS11` / KOSPI, USD → `^GSPC` / S&P 500).

**Instrument name map** (`app/models.py:Instrument`): ticker → display name is stored in a dedicated table, populated from the `name:` field per holding in the seed YAML. API endpoints return `name` alongside `ticker`; frontend shows name with the raw ticker as a muted subtitle.

**Price data shape**: `app/prices.py:_close_series` handles both flat- and multi-index yfinance DataFrames (newer yfinance versions return MultiIndex columns even for single-ticker downloads). `close_on_or_before(db, ticker, d)` is the only way snapshot code reads historical closes — it forward-fills through missing weekend/holiday rows.

## Key commands

All commands assume `.venv` (created with `python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'`).

```bash
# Test (single or all)
.venv/bin/pytest -q
.venv/bin/pytest tests/test_snapshots.py::test_late_reported_trade_updates_old_snapshots -v

# Run server locally (needs .env loaded)
.venv/bin/uvicorn app.main:create_app --factory --port 8080

# Docker (production-like)
docker compose build && docker compose up -d
docker compose exec -T app python -m app.cli seed                  # load seed/initial_holdings.yaml
docker compose exec -T app python -m app.cli backfill-prices --from 2024-01-01
docker compose exec -T app python -m app.cli recompute --from 2024-01-01
docker compose logs -f app

# Manual price refresh / recompute inside container
docker compose exec -T app python -c "
from app.db import make_engine, make_session_factory
from app.scheduler import refresh_prices_job
refresh_prices_job(make_session_factory(make_engine()))"
```

## Docker specifics

Container **must run as non-root** (compose: `user: "1000:1000"`) because the `claude` CLI refuses to run with root privileges. Auth is reused from the host via two mounts: `${HOME}/.claude → /home/appuser/.claude` *and* `${HOME}/.claude.json → /home/appuser/.claude.json` (both are needed). Rebuilding the image (`docker compose build`) is required after any change under `app/` or `web/` since `Dockerfile` uses `COPY`, not a bind mount. `docker compose restart` alone does NOT pick up code changes.

## Testing pattern

- `tests/conftest.py` provides `engine` (in-memory SQLite with `StaticPool` so TestClient connections share the DB) and `db` (Session) fixtures. All tests should depend on these.
- yfinance, FinanceDataReader, and subprocess-based `claude -p` are **always mocked** via `monkeypatch.setattr("app.prices.yf", ...)` / `"app.mcp_server.yf"` / `"app.krx_listings.fdr"` / `"app.agent.subprocess.run"`. Never hit the real network in tests.
- Tests that exercise `create_app` must pass `start_scheduler=False` to avoid leaking background threads; see `_app_with_engine` in `tests/test_api.py`.
- When changing config-dependent behavior, call `get_settings.cache_clear()` after setting env vars, or the cached Settings instance will be stale.

## Seed YAML shape

Personal positions go in `seed/initial_holdings.yaml` (gitignored). Only `seed/initial_holdings.example.yaml` is tracked. Each holding may carry a `name:` field which populates the `Instrument` table. For KRX tickers use `NNNNNN.KS` (KOSPI) or `NNNNNN.KQ` (KOSDAQ); interim post-listing codes (`NNNNzN` form) are accepted by yfinance and used as-is.

## Frontend notes

- Jinja pages inject an `asset_ver` (process-start timestamp) as a query param on `/static/*` so browsers refetch after a restart. The `NoCacheMiddleware` in `main.py` also sends `Cache-Control: no-store` for static and HTML responses.
- History chart unifies portfolio (daily) and benchmark (trading-day) series by building a union of dates and rendering each dataset with `spanGaps: true` — otherwise the benchmark line visually truncates because of Chart.js index-aligned labels.
- Currency formatting: holdings/trade prices use `maximumFractionDigits: 2`, aggregate value/cost/pnl use `0` for clarity.
- UI stack: **Tailwind CSS v4** (utility CSS with `@theme` tokens) + **Alpine.js 3** (CDN, for app-shell state: scroll-shrink header, bottom-sheet account switcher, toast) + Chart.js 4. Pretendard Variable for typography. Mobile-first with a `min-width: 768px` dock style for the bottom tab bar.
- **Important: app.js must be loaded BEFORE alpine.js** in `base.html` so the `alpine:init` listener registers stores/components before Alpine auto-starts (it calls `Alpine.start()` synchronously on module execution, not on DOMContentLoaded).
- Canvas charts: use `role="img"` with a linked `<span class="sr-only">` summary that JS rewrites after data loads. Don't pass CSS `color-mix()` to Chart.js — Canvas 2D can't parse it; use `hexToRgba()` from app.js.

## Frontend build

Tailwind is compiled to `web/static/styles.css` (gitignored; regenerated at Docker build time or via `npm run build:css` locally). Requires Node 20+.

```bash
npm install                # one-time, installs @tailwindcss/cli
npm run build:css          # one-shot minified build
npm run watch:css          # iterative dev: rebuilds on template/JS changes
```

`Dockerfile` has a dedicated `node:20-alpine` CSS-build stage so the final Python runtime image stays lean. Templates and `web/static/app.js` are scanned by Tailwind v4's `@source` directive in `web/styles.src.css` — adding a new class only requires a rebuild, no config file.

Service worker is served at `/sw.js` (via a dedicated FastAPI route in `views.py`, which sets `Service-Worker-Allowed: /` so it can control the origin root). Manifest at `/static/manifest.json`.
