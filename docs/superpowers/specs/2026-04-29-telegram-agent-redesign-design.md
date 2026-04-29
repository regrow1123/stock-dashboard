# Telegram Bot Agent Redesign — Design Spec

**Date:** 2026-04-29
**Status:** Design approved, pending implementation plan

## Background

The Telegram bot currently parses each user message via a single `claude -p` call that returns a fixed JSON shape (`app/parser.py`). The `app/telegram.py` handler then validates the JSON and either saves a Trade/Dividend or queues a `PendingConfirm` row.

This rigid contract surfaces three concrete problems:

1. **Ticker hallucination.** The LLM is asked to map a Korean stock name to a `NNNNNN.KS/.KQ` code from training data alone — no reference list of KRX listings, no validation. On 2026-04-28, `뉴로핏` was saved with the wrong ticker `418550.KQ` (actually JEIO Co., Ltd.). Investigation revealed the seed YAML's `448710.KQ` was also wrong (COTS Technology). The correct code is `380550.KQ`. Without verification this class of bug is silent — yfinance returned valid prices for the wrong ticker, so the dashboard rendered numbers that looked plausible.
2. **Missing instrument registration.** `_save_and_recompute` writes a Trade row but does **not** insert into `Instrument`. New tickers added via Telegram have no `ticker → name` mapping, so the UI displays the raw code (e.g., `278470.KS` instead of `에이피알`).
3. **Inflexibility.** The user cannot ask anything outside the parser's narrow contract — no holdings queries, no edits, no clarifying back-and-forth. Adding any capability requires a new JSON field and matching state-machine branch.

## Goal

Replace the parser/state-machine bot with an **LLM agent that has direct DB-management tools via MCP**. The agent decides when to ask, when to look up, when to save. Ticker resolution becomes one of several tools rather than a hard-coded path.

In-scope capabilities for this iteration (B scope):
- Record trade / dividend
- Cancel last trade
- Holdings & recent-activity queries
- KR Korean-name → ticker lookup; US ticker verification

Out-of-scope (deferred): edit existing trades, dividend reconciliation, complex calculations beyond what `list_holdings` exposes.

## Architecture

### Process model

Single Docker container, single FastAPI process, unchanged at the outer boundary:

```
docker compose up
└─ app (uvicorn)
   ├─ FastAPI routes (/api/*, /, /accounts/{id})            unchanged
   ├─ APScheduler (price refresh, snapshot recompute, …)    unchanged + KRX cache job
   └─ Telegram handler (poll_updates_job / webhook)         REWRITTEN
        └─ app/agent.py: build prompt → subprocess.run(["claude", "-p",
            "--mcp-config", "<path>", prompt])
             └─ claude spawns stdio MCP child:
                  python -m app.mcp_server
                   └─ same container, same DB, same env
```

The MCP server is launched per Telegram message as a stdio child of the `claude` CLI. Startup is sub-second; this matches the existing per-message subprocess cost. No long-running sidecar required, so `docker-compose.yml` is unchanged.

### Multi-turn context (sliding window)

`app/agent.py` keeps an in-memory `deque` of `(role, text, ts)` tuples per chat:

- Window size: **last 10 messages** OR **30 minutes**, whichever bounds tighter
- `>30 min` since last message ⇒ window is reset (new session)
- Not persisted to DB (acceptable to lose on restart — single-user, low volume)
- Window is rendered into the prompt under a `Recent conversation:` header before the latest user message

### MCP tool surface

Lives in `app/mcp_server.py`. Tools partition into read-only (no side effects) and write (DB mutation + downstream recompute).

**Read-only:**

| Tool | Signature | Purpose |
|---|---|---|
| `list_accounts` | `() → [{id, name, currency, broker}]` | Bootstrap context |
| `list_holdings` | `(account_id?) → [{ticker, name, qty, avg_price, current_price, value}]` | "지금 가진 거" |
| `recent_trades` | `(limit=10, account_id?) → [{id, ticker, name, side, qty, price, executed_at}]` | Cancel/identify |
| `recent_dividends` | `(limit=10, account_id?) → [...]` | Dividend history |
| `search_ticker_kr` | `(korean_name) → [{ticker, name, market}]` | FDR-backed name→code |
| `verify_ticker_us` | `(ticker) → {ticker, name_en, current_price} \| null` | yfinance check (null = not found) |
| `lookup_ticker` | `(ticker) → {ticker, name, currency, current_price}` | Cache (Instrument) → yfinance fallback |

**Write (each performs its own DB transaction + downstream effects):**

| Tool | Signature | Side effects |
|---|---|---|
| `record_trade` | `(account_id, ticker, side, qty, price, executed_at, name?)` | Trade insert, Instrument upsert if `name` given, price backfill from `executed_at - 14d`, snapshot recompute from `executed_at` |
| `record_dividend` | `(account_id, ticker, amount, paid_at, name?)` | Dividend insert, Instrument upsert if `name` given |
| `cancel_trade` | `(trade_id)` | Trade delete + snapshot recompute from trade's `executed_at` |
| `register_instrument` | `(ticker, name)` | Instrument upsert (used when user confirms a new mapping out-of-band) |

`record_trade` and `record_dividend` accept an optional `name` parameter so the LLM can populate `Instrument` in the same call when it has just resolved a new ticker. This is the explicit fix for the "278470.KS shows as the code" bug class.

### KR ticker mapping cache

New module `app/krx_listings.py`:

- `refresh_krx_cache() -> int` — calls `fdr.StockListing('KRX')`, builds in-memory dict keyed by `name → [(ticker, market)]` and `ticker → name`, persists to a pickle file (e.g., `data/krx_cache.pkl`) for fast cold-start
- `search_by_name(name: str) -> list[(ticker, market)]` — exact match first, then prefix/substring
- `get_name(ticker: str) -> str | None` — reverse lookup
- Suffix mapping: `KOSPI → .KS`, `KOSDAQ → .KQ`, `KONEX → .KN` (rare)

APScheduler job runs daily at **07:00 KST** (before market open) to refresh. Container startup hydrates from pickle; if missing, refresh immediately (blocking once).

Edge cases:
- ETFs with interim post-listing codes (e.g., `0177N0.KS`, `0126Z0.KS`) may not appear in FDR. They already exist in `Instrument` from seed, so the cache lookup ladder (Instrument → KRX cache → ask user) covers them.
- Newly-listed stocks (post-cache-refresh) fall through to "not found" → LLM asks the user.

### System prompt

`app/agent.py` builds the prompt as:

```
You are a Telegram assistant for a single-user portfolio dashboard
holding Korean and US equities. Your job is to record trade/dividend
reports, answer holdings queries, and never lose or corrupt data.

Tools: list_accounts, list_holdings, recent_trades, recent_dividends,
search_ticker_kr, verify_ticker_us, lookup_ticker, record_trade,
record_dividend, cancel_trade, register_instrument.

Resolution rules
- KR stocks: the user reports by Korean name. First try lookup_ticker on
  any guess you have; on cache miss use search_ticker_kr. If 0 candidates,
  ASK the user. If 1, proceed but mention the ticker in your reply. If
  multiple, list them and ask.
- US stocks: the user reports by ticker. Verify with verify_ticker_us.
  If null (likely typo), ASK to confirm.
- Always pass `name` to record_trade / record_dividend when you've
  resolved a new ticker — this populates the cache.

Safety
- Before calling cancel_trade, send a summary and ask 예/아니오. Wait
  for user confirmation in the NEXT message before actually calling.
- If anything is ambiguous (which account, which trade, parse failure),
  ASK rather than guess.
- Currency rule: KRW accounts hold KR tickers (.KS/.KQ); USD accounts
  hold US tickers (no suffix). Never mix.

Style
- Reply in Korean.
- ✅ for success, ❓ for confirmations, ⚠️ for problems.
- Be concise. One short paragraph or 3-5 lines max.

Recent conversation (oldest → newest):
{sliding_window or "(empty — new session)"}

Latest message from user:
{message}
```

### Safety / guardrails

The user has explicitly prioritized flexibility over rigid guardrails. Approach:

- **Soft rules in system prompt** for confirmation flows (cancel) and ambiguity handling (ask, don't guess).
- **No hard code-level blocks** on tool call counts or sequences.
- **Per-tool timeouts**: yfinance/FDR network calls bounded at 5 seconds; tool returns an error result on timeout, LLM handles in its reply.
- **No additional auth on MCP tools** — single user, container is on Tailscale, attack surface is the same as the existing FastAPI service.
- **`claude -p` itself enforces an internal max-turns** which we accept as the upper bound on tool-call loops per message.

### Migration

Files to delete:
- `app/parser.py` — entire `parse_message` and `ParseResult` interface
- `tests/test_parser.py`

Files to rewrite:
- `app/telegram.py` — `handle_message` becomes: receive message → append to window → call `app/agent.py:run_agent(text)` → send the returned reply text. The yes/no follow-up branch, the cancel-intent shortcut, the `_needs_confirm` logic, the `_save_and_recompute` helper — all go away. Webhook + polling routes themselves stay.
- `app/models.py` — drop `PendingConfirm` model and table. (One-time migration: `DROP TABLE pending_confirms;` since no rows are load-bearing.)

Files to add:
- `app/agent.py` — sliding window state, prompt assembly, subprocess invocation
- `app/mcp_server.py` — MCP tool implementations
- `app/krx_listings.py` — FDR-backed KR mapping
- `mcp.json` (or similar) — MCP server config consumed by `claude -p --mcp-config`

Dependencies to add (`pyproject.toml`):
- `finance-datareader` — KRX listing source
- `mcp` (Python SDK) — to implement the MCP server

### Testing

**Unit tests** (deterministic, network-mocked):
- `tests/test_mcp_server.py` — each tool: input → DB / output. Mock `yfinance` and `FinanceDataReader` exactly as existing tests do for prices.
- `tests/test_krx_listings.py` — cache build, search by name (exact + prefix), suffix resolution.

**Agent integration tests** (LLM-mocked):
- `tests/test_agent.py` — replay-style: monkeypatch `subprocess.run` to return canned `claude -p` outputs (text after tool-use loop). Verify the bot sends the expected reply and that pre-canned tool calls produced expected DB state.

**Manual e2e** (single round before merge):
- KR existing-cache trade ("뉴로핏 5주 22000")
- KR new ticker ("크래프톤 1주 …")
- US existing-cache trade ("LLY 1주 …")
- US typo ("AVGD 1주 …" → expect 확인 요청)
- Cancel ("방금 거 취소")
- Holdings query ("지금 카카오 계좌 뭐 가지고 있어?")
- Multi-turn ambiguity ("삼성 1주 샀어" → bot asks which account/which 삼성)

### Rollout

Single PR, single user — no feature flag. Merge after manual e2e passes. The previous `parse_message`-based code path is deleted in the same PR rather than left behind.

## Risks & open issues

1. **`claude -p` MCP support shape.** Spec assumes `claude -p --mcp-config <path>` works in non-interactive mode and runs the tool-use loop internally before returning the final text. If the CLI requires interactive mode for MCP, fall back is **B (Anthropic Python SDK + tool use)** with the user separately providing an API key. Verify in the implementation plan's first step.
2. **FDR scrape stability.** `FinanceDataReader.StockListing('KRX')` is unofficial. Mitigation: pickle cache so a transient failure doesn't break the bot; fallback to "ask the user" path covers cache misses anyway.
3. **Sliding window across container restart.** Restart drops the in-memory deque, so a multi-turn confirmation in flight is lost. User would re-issue the original message. Acceptable trade-off vs. DB persistence complexity.
4. **`PendingConfirm` table drop.** Confirm zero rows at deploy time; if any exist (in-flight confirmations), drain or migrate before drop.
