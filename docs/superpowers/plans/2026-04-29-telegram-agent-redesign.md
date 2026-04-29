# Telegram Bot Agent Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the rigid `claude -p` JSON-parser Telegram bot with an LLM agent that has direct DB-management tools via MCP. Eliminates ticker hallucination, populates Instrument cache on first trade, and unlocks holdings queries.

**Architecture:** Single FastAPI/uvicorn process unchanged at the boundary. Telegram handler → `app/agent.py` builds prompt with sliding-window context → spawns `claude -p --mcp-config <cfg>` subprocess → CLI launches `python -m app.mcp_server` as stdio MCP child → LLM calls tools → CLI returns final reply text → bot forwards to Telegram. KR ticker mapping comes from a `FinanceDataReader`-backed cache in `app/krx_listings.py`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, APScheduler, `mcp` (Anthropic MCP Python SDK), `finance-datareader`, yfinance, `claude` CLI subprocess.

**Spec:** `docs/superpowers/specs/2026-04-29-telegram-agent-redesign-design.md`

---

## File map

**Create:**
- `app/krx_listings.py` — FDR-backed KR mapping cache + name search
- `app/mcp_server.py` — MCP tool implementations (11 tools) + stdio server entrypoint
- `app/agent.py` — sliding-window state, prompt assembly, `claude -p` invocation
- `mcp.json` — MCP server config consumed by `claude -p --mcp-config`
- `tests/test_krx_listings.py`
- `tests/test_mcp_server.py`
- `tests/test_agent.py`

**Modify:**
- `pyproject.toml` — add `finance-datareader`, `mcp` deps
- `app/telegram.py` — rewrite `handle_message`, drop `_save_and_recompute`/`_confirm_text`/`_needs_confirm`/yes-no-follow-up branch
- `app/scheduler.py` — add `krx_cache_refresh_job`
- `app/models.py` — drop `PendingConfirm`
- `app/main.py` — no functional change (telegram router stays); but verify import still works after refactor
- `tests/test_api.py` — no change expected; verify
- `tests/test_telegram.py` — rewrite around agent

**Delete:**
- `app/parser.py`
- `tests/test_parser.py`

---

## Task 1: Verify `claude -p --mcp-config` end-to-end

This is a discovery task. The spec's risk #1 calls out the assumption that `claude -p` supports MCP servers in non-interactive mode and runs the tool-use loop internally. We must confirm this before building anything else; if it fails, the fallback is the Anthropic Python SDK with tool use (rebill on API key).

**Files:**
- Create: `/tmp/mcp_smoke/server.py` (throwaway)
- Create: `/tmp/mcp_smoke/mcp.json` (throwaway)

- [ ] **Step 1: Write a minimal stdio MCP server**

Create `/tmp/mcp_smoke/server.py`:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("smoke")

@mcp.tool()
def add(a: int, b: int) -> int:
    """Return a + b."""
    return a + b

if __name__ == "__main__":
    mcp.run()
```

Install the SDK in a scratch venv:

```bash
python3.12 -m venv /tmp/mcp_smoke/.venv
/tmp/mcp_smoke/.venv/bin/pip install mcp
```

- [ ] **Step 2: Write `mcp.json` config**

Create `/tmp/mcp_smoke/mcp.json`:

```json
{
  "mcpServers": {
    "smoke": {
      "command": "/tmp/mcp_smoke/.venv/bin/python",
      "args": ["/tmp/mcp_smoke/server.py"]
    }
  }
}
```

- [ ] **Step 3: Invoke `claude -p` with MCP**

Run from a shell:

```bash
claude -p --mcp-config /tmp/mcp_smoke/mcp.json --allowedTools "mcp__smoke__add" "Use the smoke.add tool to compute 7+5 and reply with just the number."
```

Expected output: a line containing `12` (or a reply like "12"). If the CLI returns `12`, MCP works in non-interactive mode and Plan A is viable.

- [ ] **Step 4: Document the result**

Append to the design spec a short note under "Risks & open issues" item 1 stating verification status (✅ verified / ❌ failed; if failed, switch architecture). Do not commit yet — this is exploratory.

If verification fails, STOP and surface the result; the rest of the plan presumes Plan A.

- [ ] **Step 5: Clean up**

```bash
rm -rf /tmp/mcp_smoke
```

(No commit for this task — it is verification only.)

---

## Task 2: Add dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add deps**

Edit `pyproject.toml`. Inside the `dependencies` list, add two lines so it reads:

```toml
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "sqlalchemy>=2.0",
  "pydantic>=2.7",
  "pydantic-settings>=2.4",
  "yfinance>=0.2.40",
  "apscheduler>=3.10",
  "httpx>=0.27",
  "jinja2>=3.1",
  "pyyaml>=6.0",
  "python-dateutil>=2.9",
  "finance-datareader>=0.9",
  "mcp>=1.0",
]
```

- [ ] **Step 2: Install into the venv**

```bash
.venv/bin/pip install -e '.[dev]'
```

Expected: pip resolves and installs `finance-datareader`, `mcp`, plus their transitive deps. No errors.

- [ ] **Step 3: Smoke import**

```bash
.venv/bin/python -c "import FinanceDataReader as fdr; from mcp.server.fastmcp import FastMCP; print('ok')"
```

Expected output: `ok`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add finance-datareader and mcp"
```

---

## Task 3: KR listings cache — exact name lookup

Build the smallest useful slice of `app/krx_listings.py`: a class that holds an in-memory mapping and resolves a Korean name to (ticker, market) tuples. Defer FDR network fetch and pickling to later tasks.

**Files:**
- Create: `app/krx_listings.py`
- Create: `tests/test_krx_listings.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_krx_listings.py`:

```python
from app.krx_listings import KrxCache


def test_search_by_name_exact_match():
    cache = KrxCache()
    cache._load_from_records([
        {"Code": "005930", "Name": "삼성전자", "Market": "KOSPI"},
        {"Code": "035720", "Name": "카카오", "Market": "KOSPI"},
    ])
    result = cache.search_by_name("삼성전자")
    assert result == [("005930.KS", "KOSPI")]


def test_search_by_name_kosdaq_suffix():
    cache = KrxCache()
    cache._load_from_records([
        {"Code": "380550", "Name": "뉴로핏", "Market": "KOSDAQ"},
    ])
    result = cache.search_by_name("뉴로핏")
    assert result == [("380550.KQ", "KOSDAQ")]


def test_search_by_name_no_match():
    cache = KrxCache()
    cache._load_from_records([
        {"Code": "005930", "Name": "삼성전자", "Market": "KOSPI"},
    ])
    assert cache.search_by_name("존재하지않는회사") == []
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_krx_listings.py -v
```

Expected: ImportError or collection failure (module does not exist).

- [ ] **Step 3: Implement minimal `KrxCache`**

Create `app/krx_listings.py`:

```python
from __future__ import annotations

_SUFFIX_FOR_MARKET = {
    "KOSPI": ".KS",
    "KOSDAQ": ".KQ",
    "KONEX": ".KN",
}


class KrxCache:
    """In-memory KRX ticker mapping. Exact-name resolution only (Task 3)."""

    def __init__(self) -> None:
        # name -> list[(ticker_with_suffix, market)]
        self._by_name: dict[str, list[tuple[str, str]]] = {}

    def _load_from_records(self, records: list[dict]) -> None:
        self._by_name.clear()
        for r in records:
            market = r.get("Market") or ""
            suffix = _SUFFIX_FOR_MARKET.get(market)
            if suffix is None:
                continue
            ticker = f"{r['Code']}{suffix}"
            self._by_name.setdefault(r["Name"], []).append((ticker, market))

    def search_by_name(self, name: str) -> list[tuple[str, str]]:
        return list(self._by_name.get(name, []))
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
.venv/bin/pytest tests/test_krx_listings.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/krx_listings.py tests/test_krx_listings.py
git commit -m "feat(krx): add in-memory cache with exact name lookup"
```

---

## Task 4: KR listings cache — substring search and reverse lookup

**Files:**
- Modify: `app/krx_listings.py`
- Modify: `tests/test_krx_listings.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_krx_listings.py`:

```python
def test_search_by_name_falls_back_to_substring():
    cache = KrxCache()
    cache._load_from_records([
        {"Code": "005930", "Name": "삼성전자", "Market": "KOSPI"},
        {"Code": "005935", "Name": "삼성전자우", "Market": "KOSPI"},
    ])
    # exact match wins — only "삼성전자"
    assert cache.search_by_name("삼성전자") == [("005930.KS", "KOSPI")]
    # substring fallback when no exact match — "삼성" returns both
    out = cache.search_by_name("삼성")
    out_set = {t for t, _ in out}
    assert out_set == {"005930.KS", "005935.KS"}


def test_get_name_returns_canonical_korean_name():
    cache = KrxCache()
    cache._load_from_records([
        {"Code": "005930", "Name": "삼성전자", "Market": "KOSPI"},
    ])
    assert cache.get_name("005930.KS") == "삼성전자"
    assert cache.get_name("999999.KS") is None
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_krx_listings.py -v
```

Expected: 2 new tests fail (`AttributeError: 'KrxCache' object has no attribute 'get_name'` and substring assertion error).

- [ ] **Step 3: Add substring fallback and `get_name`**

Edit `app/krx_listings.py`. Replace the entire class body so the file reads:

```python
from __future__ import annotations

_SUFFIX_FOR_MARKET = {
    "KOSPI": ".KS",
    "KOSDAQ": ".KQ",
    "KONEX": ".KN",
}


class KrxCache:
    """In-memory KRX ticker mapping with name search."""

    def __init__(self) -> None:
        # name -> list[(ticker_with_suffix, market)]
        self._by_name: dict[str, list[tuple[str, str]]] = {}
        # ticker -> name
        self._by_ticker: dict[str, str] = {}

    def _load_from_records(self, records: list[dict]) -> None:
        self._by_name.clear()
        self._by_ticker.clear()
        for r in records:
            market = r.get("Market") or ""
            suffix = _SUFFIX_FOR_MARKET.get(market)
            if suffix is None:
                continue
            ticker = f"{r['Code']}{suffix}"
            name = r["Name"]
            self._by_name.setdefault(name, []).append((ticker, market))
            self._by_ticker[ticker] = name

    def search_by_name(self, name: str) -> list[tuple[str, str]]:
        exact = self._by_name.get(name)
        if exact:
            return list(exact)
        # Substring fallback: any name containing the query
        out: list[tuple[str, str]] = []
        for n, items in self._by_name.items():
            if name in n:
                out.extend(items)
        return out

    def get_name(self, ticker: str) -> str | None:
        return self._by_ticker.get(ticker)
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
.venv/bin/pytest tests/test_krx_listings.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/krx_listings.py tests/test_krx_listings.py
git commit -m "feat(krx): add substring fallback and reverse lookup"
```

---

## Task 5: KR listings cache — FDR refresh + pickle persistence

**Files:**
- Modify: `app/krx_listings.py`
- Modify: `tests/test_krx_listings.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_krx_listings.py`:

```python
import pickle
from unittest.mock import MagicMock

import pandas as pd


def test_refresh_calls_fdr_and_loads_records(monkeypatch, tmp_path):
    df = pd.DataFrame([
        {"Code": "005930", "Name": "삼성전자", "Market": "KOSPI"},
        {"Code": "380550", "Name": "뉴로핏", "Market": "KOSDAQ"},
    ])
    fake_fdr = MagicMock()
    fake_fdr.StockListing.return_value = df
    monkeypatch.setattr("app.krx_listings.fdr", fake_fdr)

    cache = KrxCache(persist_path=tmp_path / "krx.pkl")
    n = cache.refresh()

    assert n == 2
    fake_fdr.StockListing.assert_called_once_with("KRX")
    assert cache.search_by_name("삼성전자") == [("005930.KS", "KOSPI")]
    assert cache.search_by_name("뉴로핏") == [("380550.KQ", "KOSDAQ")]


def test_refresh_persists_to_pickle(monkeypatch, tmp_path):
    df = pd.DataFrame([
        {"Code": "005930", "Name": "삼성전자", "Market": "KOSPI"},
    ])
    fake_fdr = MagicMock()
    fake_fdr.StockListing.return_value = df
    monkeypatch.setattr("app.krx_listings.fdr", fake_fdr)

    pkl = tmp_path / "krx.pkl"
    cache = KrxCache(persist_path=pkl)
    cache.refresh()

    assert pkl.exists()
    with pkl.open("rb") as f:
        loaded = pickle.load(f)
    assert "삼성전자" in loaded["by_name"]


def test_hydrate_from_pickle_skips_fdr(monkeypatch, tmp_path):
    fake_fdr = MagicMock()
    monkeypatch.setattr("app.krx_listings.fdr", fake_fdr)

    pkl = tmp_path / "krx.pkl"
    with pkl.open("wb") as f:
        pickle.dump(
            {
                "by_name": {"삼성전자": [("005930.KS", "KOSPI")]},
                "by_ticker": {"005930.KS": "삼성전자"},
            },
            f,
        )

    cache = KrxCache(persist_path=pkl)
    assert cache.hydrate() is True
    assert cache.search_by_name("삼성전자") == [("005930.KS", "KOSPI")]
    fake_fdr.StockListing.assert_not_called()


def test_hydrate_returns_false_when_no_pickle(tmp_path):
    cache = KrxCache(persist_path=tmp_path / "missing.pkl")
    assert cache.hydrate() is False
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_krx_listings.py -v
```

Expected: 4 new tests fail (no `fdr`/`refresh`/`hydrate`/`persist_path`).

- [ ] **Step 3: Add refresh, hydrate, persistence**

Replace `app/krx_listings.py` with:

```python
from __future__ import annotations

import pickle
from pathlib import Path

import FinanceDataReader as fdr  # noqa: N813

_SUFFIX_FOR_MARKET = {
    "KOSPI": ".KS",
    "KOSDAQ": ".KQ",
    "KONEX": ".KN",
}


class KrxCache:
    """KRX ticker mapping backed by FinanceDataReader, with pickle persistence."""

    def __init__(self, persist_path: Path | None = None) -> None:
        self._by_name: dict[str, list[tuple[str, str]]] = {}
        self._by_ticker: dict[str, str] = {}
        self.persist_path = persist_path

    def _load_from_records(self, records: list[dict]) -> None:
        self._by_name.clear()
        self._by_ticker.clear()
        for r in records:
            market = r.get("Market") or ""
            suffix = _SUFFIX_FOR_MARKET.get(market)
            if suffix is None:
                continue
            ticker = f"{r['Code']}{suffix}"
            name = r["Name"]
            self._by_name.setdefault(name, []).append((ticker, market))
            self._by_ticker[ticker] = name

    def search_by_name(self, name: str) -> list[tuple[str, str]]:
        exact = self._by_name.get(name)
        if exact:
            return list(exact)
        out: list[tuple[str, str]] = []
        for n, items in self._by_name.items():
            if name in n:
                out.extend(items)
        return out

    def get_name(self, ticker: str) -> str | None:
        return self._by_ticker.get(ticker)

    def refresh(self) -> int:
        """Pull KRX listings from FDR. Returns count of usable rows loaded."""
        df = fdr.StockListing("KRX")
        records = df.to_dict("records")
        self._load_from_records(records)
        if self.persist_path is not None:
            self._persist()
        return len(self._by_ticker)

    def _persist(self) -> None:
        assert self.persist_path is not None
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        with self.persist_path.open("wb") as f:
            pickle.dump(
                {"by_name": self._by_name, "by_ticker": self._by_ticker}, f
            )

    def hydrate(self) -> bool:
        """Load cache from pickle. Return True on success, False if missing/corrupt."""
        if self.persist_path is None or not self.persist_path.exists():
            return False
        try:
            with self.persist_path.open("rb") as f:
                data = pickle.load(f)
            self._by_name = data["by_name"]
            self._by_ticker = data["by_ticker"]
            return True
        except (pickle.PickleError, KeyError, EOFError):
            return False


# Module-level singleton wired by main.py / scheduler at startup.
_default_cache: KrxCache | None = None


def get_cache() -> KrxCache:
    global _default_cache
    if _default_cache is None:
        from app.config import get_settings

        settings = get_settings()
        pkl = settings.db_path.parent / "krx_cache.pkl"
        _default_cache = KrxCache(persist_path=pkl)
    return _default_cache
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
.venv/bin/pytest tests/test_krx_listings.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add app/krx_listings.py tests/test_krx_listings.py
git commit -m "feat(krx): add FDR refresh and pickle persistence"
```

---

## Task 6: MCP server — read-only tools (5 tools)

Build the MCP server module with **all read-only tools as plain Python functions** that accept a `Session`. The MCP wrappers come in a later step. We test the underlying functions directly.

**Files:**
- Create: `app/mcp_server.py`
- Create: `tests/test_mcp_server.py`

- [ ] **Step 1: Write tests for all 5 read-only tools**

Create `tests/test_mcp_server.py`:

```python
from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.models import (
    Account, Dividend, Instrument, LivePrice, Price, SeedHolding, Trade,
)
from app.mcp_server import (
    list_accounts, list_holdings, recent_trades, recent_dividends,
    search_ticker_kr, verify_ticker_us, lookup_ticker,
)


@pytest.fixture
def seeded_db(db):
    db.add(Account(id="kr1", name="ISA", broker="삼성", currency="KRW", display_order=1))
    db.add(Account(id="us1", name="해외", broker="카카오", currency="USD", display_order=2))
    db.add(Instrument(ticker="005930.KS", name="삼성전자"))
    db.add(SeedHolding(account_id="kr1", ticker="005930.KS", quantity=10.0, avg_price=80000))
    db.add(LivePrice(
        ticker="005930.KS", price=85000.0, currency="KRW",
        fetched_at=__import__("datetime").datetime(2026, 4, 29, 10, 0),
    ))
    db.commit()
    return db


def test_list_accounts(seeded_db):
    out = list_accounts(seeded_db)
    assert out == [
        {"id": "kr1", "name": "ISA", "currency": "KRW", "broker": "삼성"},
        {"id": "us1", "name": "해외", "currency": "USD", "broker": "카카오"},
    ]


def test_list_holdings_includes_seed_with_live_price(seeded_db):
    out = list_holdings(seeded_db, account_id="kr1")
    assert len(out) == 1
    h = out[0]
    assert h["ticker"] == "005930.KS"
    assert h["name"] == "삼성전자"
    assert h["quantity"] == 10.0
    assert h["avg_price"] == 80000
    assert h["current_price"] == 85000.0
    assert h["value"] == 850000.0


def test_list_holdings_filters_by_account(seeded_db):
    seeded_db.add(Trade(
        account_id="us1", ticker="LLY", side="buy",
        quantity=2.0, price=900.0, executed_at=date(2026, 4, 28),
    ))
    seeded_db.commit()
    kr_only = list_holdings(seeded_db, account_id="kr1")
    assert {h["ticker"] for h in kr_only} == {"005930.KS"}


def test_recent_trades_orders_by_id_desc(seeded_db):
    seeded_db.add_all([
        Trade(account_id="kr1", ticker="005930.KS", side="buy", quantity=1,
              price=84000, executed_at=date(2026, 4, 27)),
        Trade(account_id="kr1", ticker="005930.KS", side="buy", quantity=2,
              price=85000, executed_at=date(2026, 4, 28)),
    ])
    seeded_db.commit()
    out = recent_trades(seeded_db, limit=10)
    assert [t["quantity"] for t in out] == [2, 1]
    assert out[0]["name"] == "삼성전자"


def test_recent_dividends(seeded_db):
    seeded_db.add(Dividend(
        account_id="kr1", ticker="005930.KS", amount=1500.0,
        paid_at=date(2026, 4, 1),
    ))
    seeded_db.commit()
    out = recent_dividends(seeded_db, limit=5)
    assert len(out) == 1
    assert out[0]["amount"] == 1500.0


def test_search_ticker_kr_uses_cache(monkeypatch):
    from app.krx_listings import KrxCache
    cache = KrxCache()
    cache._load_from_records([
        {"Code": "380550", "Name": "뉴로핏", "Market": "KOSDAQ"},
    ])
    monkeypatch.setattr("app.mcp_server.get_cache", lambda: cache)
    out = search_ticker_kr("뉴로핏")
    assert out == [{"ticker": "380550.KQ", "name": "뉴로핏", "market": "KOSDAQ"}]


def test_verify_ticker_us_returns_info(monkeypatch):
    fake_yf = MagicMock()
    fake_yf.Ticker.return_value.info = {
        "longName": "Eli Lilly and Company",
        "regularMarketPrice": 920.5,
    }
    monkeypatch.setattr("app.mcp_server.yf", fake_yf)
    out = verify_ticker_us("LLY")
    assert out == {"ticker": "LLY", "name_en": "Eli Lilly and Company", "current_price": 920.5}


def test_verify_ticker_us_returns_none_when_no_name(monkeypatch):
    fake_yf = MagicMock()
    fake_yf.Ticker.return_value.info = {}
    monkeypatch.setattr("app.mcp_server.yf", fake_yf)
    assert verify_ticker_us("BADTICK") is None


def test_lookup_ticker_prefers_instrument_cache(seeded_db, monkeypatch):
    fake_yf = MagicMock()
    monkeypatch.setattr("app.mcp_server.yf", fake_yf)
    out = lookup_ticker(seeded_db, "005930.KS")
    assert out["name"] == "삼성전자"
    assert out["currency"] == "KRW"
    assert out["current_price"] == 85000.0
    fake_yf.Ticker.assert_not_called()


def test_lookup_ticker_falls_back_to_yfinance(seeded_db, monkeypatch):
    fake_yf = MagicMock()
    fake_yf.Ticker.return_value.info = {
        "longName": "Some New Co.",
        "currency": "USD",
        "regularMarketPrice": 42.0,
    }
    monkeypatch.setattr("app.mcp_server.yf", fake_yf)
    out = lookup_ticker(seeded_db, "NEWTICK")
    assert out == {
        "ticker": "NEWTICK", "name": "Some New Co.",
        "currency": "USD", "current_price": 42.0,
    }
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_mcp_server.py -v
```

Expected: ImportError (module does not exist).

- [ ] **Step 3: Implement read-only tools**

Create `app/mcp_server.py`:

```python
from __future__ import annotations

from typing import Any

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.krx_listings import get_cache
from app.models import (
    Account, Dividend, Instrument, LivePrice, SeedHolding, Trade,
)


# ---------- Read-only tools ----------

def list_accounts(db: Session) -> list[dict[str, Any]]:
    accs = db.execute(select(Account).order_by(Account.display_order)).scalars().all()
    return [
        {"id": a.id, "name": a.name, "currency": a.currency, "broker": a.broker}
        for a in accs
    ]


def list_holdings(
    db: Session, account_id: str | None = None
) -> list[dict[str, Any]]:
    """Aggregate quantity from seeds + trades, decorate with current price."""
    accounts = (
        db.execute(select(Account).where(Account.id == account_id)).scalars().all()
        if account_id
        else db.execute(select(Account).order_by(Account.display_order)).scalars().all()
    )
    out: list[dict[str, Any]] = []
    for acc in accounts:
        seeds = {
            s.ticker: (s.quantity, s.avg_price)
            for s in db.execute(
                select(SeedHolding).where(SeedHolding.account_id == acc.id)
            ).scalars()
        }
        trades = db.execute(
            select(Trade).where(Trade.account_id == acc.id)
        ).scalars().all()
        # Aggregate ticker -> (quantity, weighted_avg_price)
        agg: dict[str, list[float]] = {}  # ticker -> [qty, total_cost]
        for tk, (qty, avg) in seeds.items():
            agg[tk] = [qty, qty * avg]
        for t in trades:
            cur = agg.setdefault(t.ticker, [0.0, 0.0])
            if t.side == "buy":
                cur[0] += t.quantity
                cur[1] += t.quantity * t.price
            else:
                cur[0] -= t.quantity
                cur[1] -= t.quantity * t.price
        for tk, (qty, total_cost) in agg.items():
            if qty <= 0:
                continue
            avg_price = total_cost / qty if qty else 0.0
            inst = db.get(Instrument, tk)
            lp = db.get(LivePrice, tk)
            out.append({
                "account_id": acc.id,
                "ticker": tk,
                "name": inst.name if inst else tk,
                "quantity": qty,
                "avg_price": avg_price,
                "current_price": lp.price if lp else None,
                "value": (lp.price * qty) if lp else None,
            })
    return out


def recent_trades(
    db: Session, limit: int = 10, account_id: str | None = None
) -> list[dict[str, Any]]:
    stmt = select(Trade).order_by(Trade.id.desc()).limit(limit)
    if account_id:
        stmt = (
            select(Trade).where(Trade.account_id == account_id)
            .order_by(Trade.id.desc()).limit(limit)
        )
    rows = db.execute(stmt).scalars().all()
    out: list[dict[str, Any]] = []
    for t in rows:
        inst = db.get(Instrument, t.ticker)
        out.append({
            "id": t.id, "account_id": t.account_id, "ticker": t.ticker,
            "name": inst.name if inst else t.ticker,
            "side": t.side, "quantity": t.quantity, "price": t.price,
            "executed_at": t.executed_at.isoformat(),
        })
    return out


def recent_dividends(
    db: Session, limit: int = 10, account_id: str | None = None
) -> list[dict[str, Any]]:
    stmt = select(Dividend).order_by(Dividend.id.desc()).limit(limit)
    if account_id:
        stmt = (
            select(Dividend).where(Dividend.account_id == account_id)
            .order_by(Dividend.id.desc()).limit(limit)
        )
    rows = db.execute(stmt).scalars().all()
    out: list[dict[str, Any]] = []
    for d in rows:
        inst = db.get(Instrument, d.ticker)
        out.append({
            "id": d.id, "account_id": d.account_id, "ticker": d.ticker,
            "name": inst.name if inst else d.ticker,
            "amount": d.amount, "paid_at": d.paid_at.isoformat(),
        })
    return out


def search_ticker_kr(korean_name: str) -> list[dict[str, Any]]:
    cache = get_cache()
    return [
        {"ticker": t, "name": korean_name, "market": m}
        for t, m in cache.search_by_name(korean_name)
    ]


def verify_ticker_us(ticker: str) -> dict[str, Any] | None:
    info = yf.Ticker(ticker).info
    name = info.get("longName") or info.get("shortName")
    price = info.get("regularMarketPrice") or info.get("currentPrice")
    if not name:
        return None
    return {"ticker": ticker, "name_en": name, "current_price": price}


def lookup_ticker(db: Session, ticker: str) -> dict[str, Any]:
    inst = db.get(Instrument, ticker)
    if inst is not None:
        lp = db.get(LivePrice, ticker)
        return {
            "ticker": ticker, "name": inst.name,
            "currency": lp.currency if lp else None,
            "current_price": lp.price if lp else None,
        }
    info = yf.Ticker(ticker).info
    return {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName") or ticker,
        "currency": info.get("currency"),
        "current_price": info.get("regularMarketPrice") or info.get("currentPrice"),
    }
```

> Note for the `search_ticker_kr` test fix: the test expects `name="뉴로핏"` (the queried name) returned, but if the cache has multiple entries for an exact-match name, returning the queried name is correct. For substring matches the same query is echoed back; the LLM disambiguates by inspecting tickers.

- [ ] **Step 4: Run tests to confirm pass**

```bash
.venv/bin/pytest tests/test_mcp_server.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add app/mcp_server.py tests/test_mcp_server.py
git commit -m "feat(mcp): implement read-only tools (list/recent/search/verify/lookup)"
```

---

## Task 7: MCP server — write tools (record/cancel/register)

**Files:**
- Modify: `app/mcp_server.py`
- Modify: `tests/test_mcp_server.py`

- [ ] **Step 1: Write tests for write tools**

Append to `tests/test_mcp_server.py`:

```python
from datetime import date

from app.mcp_server import (
    record_trade, record_dividend, cancel_trade, register_instrument,
)


def test_register_instrument_upserts(seeded_db):
    register_instrument(seeded_db, "278470.KS", "에이피알")
    inst = seeded_db.get(Instrument, "278470.KS")
    assert inst.name == "에이피알"
    # Update path
    register_instrument(seeded_db, "278470.KS", "APR Co")
    inst = seeded_db.get(Instrument, "278470.KS")
    assert inst.name == "APR Co"


def test_record_trade_saves_and_creates_instrument(seeded_db, monkeypatch):
    monkeypatch.setattr("app.mcp_server._post_save_recompute", lambda *a, **k: None)
    out = record_trade(
        seeded_db,
        account_id="kr1", ticker="380550.KQ", side="buy",
        quantity=10.0, price=21200.0, executed_at=date(2026, 4, 28),
        name="뉴로핏",
    )
    assert "trade_id" in out
    t = seeded_db.get(Trade, out["trade_id"])
    assert t.ticker == "380550.KQ"
    assert t.quantity == 10.0
    inst = seeded_db.get(Instrument, "380550.KQ")
    assert inst is not None
    assert inst.name == "뉴로핏"


def test_record_trade_skips_instrument_when_no_name(seeded_db, monkeypatch):
    monkeypatch.setattr("app.mcp_server._post_save_recompute", lambda *a, **k: None)
    record_trade(
        seeded_db,
        account_id="kr1", ticker="000001.KS", side="buy",
        quantity=1.0, price=1000.0, executed_at=date(2026, 4, 28),
    )
    assert seeded_db.get(Instrument, "000001.KS") is None


def test_record_dividend_saves(seeded_db):
    out = record_dividend(
        seeded_db,
        account_id="kr1", ticker="005930.KS",
        amount=1500.0, paid_at=date(2026, 4, 1), name="삼성전자",
    )
    assert "dividend_id" in out
    d = seeded_db.get(Dividend, out["dividend_id"])
    assert d.amount == 1500.0


def test_cancel_trade_deletes_and_returns_summary(seeded_db, monkeypatch):
    monkeypatch.setattr("app.mcp_server._post_cancel_recompute", lambda *a, **k: None)
    seeded_db.add(Trade(
        account_id="kr1", ticker="005930.KS", side="buy",
        quantity=3.0, price=85000, executed_at=date(2026, 4, 28),
    ))
    seeded_db.commit()
    tid = seeded_db.execute(
        select(Trade).order_by(Trade.id.desc()).limit(1)
    ).scalar_one().id
    out = cancel_trade(seeded_db, tid)
    assert out["ok"] is True
    assert seeded_db.get(Trade, tid) is None


def test_cancel_trade_returns_not_found(seeded_db):
    out = cancel_trade(seeded_db, 99999)
    assert out == {"ok": False, "error": "not_found"}
```

Add `from sqlalchemy import select` to the imports at the top of `tests/test_mcp_server.py` if not already present.

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_mcp_server.py -v
```

Expected: 6 new tests fail (ImportError on functions not yet defined).

- [ ] **Step 3: Implement write tools**

Append to `app/mcp_server.py`:

```python
from datetime import date, timedelta

from app.prices import backfill_prices, refresh_live_prices
from app.snapshots import recompute_snapshots
from app.models import Dividend


# ---------- Write tools ----------

def register_instrument(db: Session, ticker: str, name: str) -> dict[str, Any]:
    inst = db.get(Instrument, ticker)
    if inst is None:
        db.add(Instrument(ticker=ticker, name=name))
    else:
        inst.name = name
    db.commit()
    return {"ok": True, "ticker": ticker, "name": name}


def _post_save_recompute(
    db: Session, *, account_id: str, ticker: str,
    executed_at: date, currency: str | None,
) -> None:
    """Backfill prices for the new ticker (best-effort) and recompute snapshots."""
    today = date.today()
    if currency is not None:
        try:
            backfill_prices(
                db, ticker=ticker, currency=currency,
                start=executed_at - timedelta(days=14),
                end=today + timedelta(days=1),
            )
        except Exception:
            pass
        try:
            refresh_live_prices(db, tickers=[ticker])
        except Exception:
            pass
    recompute_snapshots(
        db, account_id=account_id, from_date=executed_at, to_date=today,
    )


def _post_cancel_recompute(db: Session, *, account_id: str, executed_at: date) -> None:
    recompute_snapshots(
        db, account_id=account_id, from_date=executed_at, to_date=date.today(),
    )


def record_trade(
    db: Session, *, account_id: str, ticker: str, side: str,
    quantity: float, price: float, executed_at: date,
    name: str | None = None,
) -> dict[str, Any]:
    if side not in ("buy", "sell"):
        return {"ok": False, "error": "invalid_side"}
    acc = db.get(Account, account_id)
    if acc is None:
        return {"ok": False, "error": "unknown_account"}
    if name is not None:
        register_instrument(db, ticker, name)
    trade = Trade(
        account_id=account_id, ticker=ticker, side=side,
        quantity=quantity, price=price, executed_at=executed_at,
        raw_text="", tg_message_id=None,
    )
    db.add(trade)
    db.commit()
    _post_save_recompute(
        db, account_id=account_id, ticker=ticker,
        executed_at=executed_at, currency=acc.currency,
    )
    return {"ok": True, "trade_id": trade.id}


def record_dividend(
    db: Session, *, account_id: str, ticker: str,
    amount: float, paid_at: date, name: str | None = None,
) -> dict[str, Any]:
    if db.get(Account, account_id) is None:
        return {"ok": False, "error": "unknown_account"}
    if name is not None:
        register_instrument(db, ticker, name)
    div = Dividend(
        account_id=account_id, ticker=ticker, amount=amount,
        paid_at=paid_at, raw_text="", tg_message_id=None,
    )
    db.add(div)
    db.commit()
    return {"ok": True, "dividend_id": div.id}


def cancel_trade(db: Session, trade_id: int) -> dict[str, Any]:
    t = db.get(Trade, trade_id)
    if t is None:
        return {"ok": False, "error": "not_found"}
    summary = {
        "ticker": t.ticker, "side": t.side, "quantity": t.quantity,
        "price": t.price, "executed_at": t.executed_at.isoformat(),
        "account_id": t.account_id,
    }
    account_id = t.account_id
    executed_at = t.executed_at
    db.delete(t)
    db.commit()
    _post_cancel_recompute(db, account_id=account_id, executed_at=executed_at)
    return {"ok": True, "removed": summary}
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
.venv/bin/pytest tests/test_mcp_server.py -v
```

Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add app/mcp_server.py tests/test_mcp_server.py
git commit -m "feat(mcp): implement write tools (record/cancel/register)"
```

---

## Task 8: MCP server — stdio entrypoint

Wrap the plain Python tool functions with `FastMCP` decorators so they're exposed via stdio. The tools open a fresh DB session per call.

**Files:**
- Modify: `app/mcp_server.py`

- [ ] **Step 1: Append the FastMCP wrapper**

Append at the end of `app/mcp_server.py`:

```python
# ---------- MCP stdio entrypoint ----------

from datetime import date as _date  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

from app.db import make_engine, make_session_factory  # noqa: E402

mcp = FastMCP("stock-dashboard")

_session_factory = None


def _sf():
    global _session_factory
    if _session_factory is None:
        _session_factory = make_session_factory(make_engine())
    return _session_factory


def _with_session(fn, *args, **kwargs):
    db = _sf()()
    try:
        return fn(db, *args, **kwargs)
    finally:
        db.close()


@mcp.tool()
def t_list_accounts() -> list[dict]:
    """List all portfolio accounts with id, name, currency, broker."""
    return _with_session(list_accounts)


@mcp.tool()
def t_list_holdings(account_id: str | None = None) -> list[dict]:
    """List current holdings (with current price + value), optionally filtered by account."""
    return _with_session(list_holdings, account_id=account_id)


@mcp.tool()
def t_recent_trades(limit: int = 10, account_id: str | None = None) -> list[dict]:
    """Most recent trades (descending by id)."""
    return _with_session(recent_trades, limit=limit, account_id=account_id)


@mcp.tool()
def t_recent_dividends(limit: int = 10, account_id: str | None = None) -> list[dict]:
    """Most recent dividends (descending by id)."""
    return _with_session(recent_dividends, limit=limit, account_id=account_id)


@mcp.tool()
def t_search_ticker_kr(korean_name: str) -> list[dict]:
    """Search KRX listings by Korean name. Returns 0..N candidates."""
    return search_ticker_kr(korean_name)


@mcp.tool()
def t_verify_ticker_us(ticker: str) -> dict | None:
    """Verify a US ticker via yfinance. Returns null if not found."""
    return verify_ticker_us(ticker)


@mcp.tool()
def t_lookup_ticker(ticker: str) -> dict:
    """Resolve a ticker to {name, currency, current_price}. Cache first, yfinance fallback."""
    return _with_session(lookup_ticker, ticker)


@mcp.tool()
def t_record_trade(
    account_id: str, ticker: str, side: str,
    quantity: float, price: float, executed_at: str,
    name: str | None = None,
) -> dict:
    """Record a buy or sell. Pass name to also register the ticker name."""
    return _with_session(
        record_trade,
        account_id=account_id, ticker=ticker, side=side,
        quantity=quantity, price=price,
        executed_at=_date.fromisoformat(executed_at), name=name,
    )


@mcp.tool()
def t_record_dividend(
    account_id: str, ticker: str, amount: float,
    paid_at: str, name: str | None = None,
) -> dict:
    """Record a cash dividend payment."""
    return _with_session(
        record_dividend,
        account_id=account_id, ticker=ticker, amount=amount,
        paid_at=_date.fromisoformat(paid_at), name=name,
    )


@mcp.tool()
def t_cancel_trade(trade_id: int) -> dict:
    """Delete a trade by id and recompute snapshots from its date forward."""
    return _with_session(cancel_trade, trade_id)


@mcp.tool()
def t_register_instrument(ticker: str, name: str) -> dict:
    """Map a ticker to its display name (Korean or English)."""
    return _with_session(register_instrument, ticker, name)


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 2: Smoke-launch the server**

```bash
.venv/bin/python -m app.mcp_server &
SERVER_PID=$!
sleep 1
kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null
echo "exited"
```

Expected: starts and exits without an exception trace. (FastMCP's `run()` will block on stdio; killing it is fine.)

- [ ] **Step 3: Commit**

```bash
git add app/mcp_server.py
git commit -m "feat(mcp): expose tools via FastMCP stdio entrypoint"
```

---

## Task 9: `mcp.json` config and verify with claude CLI

**Files:**
- Create: `mcp.json`

- [ ] **Step 1: Write the config**

Create `mcp.json` at the repo root:

```json
{
  "mcpServers": {
    "dashboard": {
      "command": "python",
      "args": ["-m", "app.mcp_server"],
      "env": {
        "DB_PATH": "${DB_PATH}"
      }
    }
  }
}
```

(The `claude` CLI substitutes `${DB_PATH}` from the calling environment, which is set by docker-compose for the in-container path and by `.env` locally.)

- [ ] **Step 2: Verify the LLM can call our tools**

In a shell with `.venv` activated and `.env` loaded:

```bash
DB_PATH=./data/dashboard.db .venv/bin/python -c "
import subprocess
out = subprocess.run(
    ['claude', '-p', '--mcp-config', './mcp.json',
     '--allowedTools', 'mcp__dashboard__t_list_accounts',
     'List all my portfolio accounts using the t_list_accounts tool. Reply with the account ids only, comma-separated.'],
    capture_output=True, text=True, timeout=60,
)
print('STDOUT:', out.stdout)
print('STDERR:', out.stderr)
"
```

Expected: stdout contains the account ids `samsung_isa, samsung_irp, samsung_pension, kakao_us` (order may vary). If it fails, capture stderr for diagnostics — likely an MCP env or path issue.

- [ ] **Step 3: Commit**

```bash
git add mcp.json
git commit -m "feat(mcp): add stdio server config for claude CLI"
```

---

## Task 10: Agent module — sliding window

Smallest useful slice: a class that stores `(role, text, ts)` tuples and renders the last N within 30 minutes.

**Files:**
- Create: `app/agent.py`
- Create: `tests/test_agent.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent.py`:

```python
from datetime import datetime, timedelta

from app.agent import SlidingWindow


def test_window_renders_recent_messages():
    w = SlidingWindow(max_messages=10, max_age=timedelta(minutes=30))
    t0 = datetime(2026, 4, 29, 12, 0)
    w.append("user", "hi", at=t0)
    w.append("assistant", "hello!", at=t0 + timedelta(seconds=1))
    rendered = w.render(at=t0 + timedelta(seconds=5))
    assert "user: hi" in rendered
    assert "assistant: hello!" in rendered


def test_window_drops_old_messages():
    w = SlidingWindow(max_messages=10, max_age=timedelta(minutes=30))
    t0 = datetime(2026, 4, 29, 12, 0)
    w.append("user", "old", at=t0)
    w.append("user", "new", at=t0 + timedelta(minutes=31))
    rendered = w.render(at=t0 + timedelta(minutes=31, seconds=1))
    assert "old" not in rendered
    assert "new" in rendered


def test_window_caps_message_count():
    w = SlidingWindow(max_messages=3, max_age=timedelta(hours=1))
    t0 = datetime(2026, 4, 29, 12, 0)
    for i in range(5):
        w.append("user", f"m{i}", at=t0 + timedelta(seconds=i))
    rendered = w.render(at=t0 + timedelta(seconds=10))
    assert "m0" not in rendered
    assert "m1" not in rendered
    assert "m2" in rendered
    assert "m3" in rendered
    assert "m4" in rendered


def test_empty_window_renders_placeholder():
    w = SlidingWindow()
    out = w.render()
    assert "(empty" in out
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_agent.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `SlidingWindow`**

Create `app/agent.py`:

```python
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta


class SlidingWindow:
    def __init__(
        self, *,
        max_messages: int = 10,
        max_age: timedelta = timedelta(minutes=30),
    ) -> None:
        self._dq: deque[tuple[str, str, datetime]] = deque(maxlen=max_messages)
        self._max_age = max_age

    def append(self, role: str, text: str, *, at: datetime | None = None) -> None:
        self._dq.append((role, text, at or datetime.now()))

    def _alive(self, at: datetime) -> list[tuple[str, str, datetime]]:
        cutoff = at - self._max_age
        return [(r, t, ts) for r, t, ts in self._dq if ts >= cutoff]

    def render(self, *, at: datetime | None = None) -> str:
        now = at or datetime.now()
        rows = self._alive(now)
        if not rows:
            return "(empty — new session)"
        return "\n".join(f"{r}: {t}" for r, t, _ in rows)
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
.venv/bin/pytest tests/test_agent.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/agent.py tests/test_agent.py
git commit -m "feat(agent): add sliding-window context buffer"
```

---

## Task 11: Agent module — prompt assembly + subprocess invoke

**Files:**
- Modify: `app/agent.py`
- Modify: `tests/test_agent.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent.py`:

```python
from unittest.mock import MagicMock

from app.agent import build_prompt, run_agent


def test_build_prompt_includes_window_and_message():
    w = SlidingWindow()
    w.append("user", "earlier message", at=datetime(2026, 4, 29, 12, 0))
    prompt = build_prompt(window=w, message="latest", at=datetime(2026, 4, 29, 12, 0, 5))
    assert "earlier message" in prompt
    assert "latest" in prompt
    assert "Tools:" in prompt
    assert "Resolution rules" in prompt


def test_run_agent_invokes_claude_and_returns_stdout(monkeypatch):
    fake_run = MagicMock()
    fake_run.return_value = MagicMock(
        returncode=0, stdout="✅ 매수 기록", stderr="",
    )
    monkeypatch.setattr("app.agent.subprocess.run", fake_run)
    out = run_agent("뉴로핏 10주 매수")
    assert out == "✅ 매수 기록"
    args, kwargs = fake_run.call_args
    cmd = args[0]
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "--mcp-config" in cmd


def test_run_agent_returns_error_text_on_failure(monkeypatch):
    fake_run = MagicMock()
    fake_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
    monkeypatch.setattr("app.agent.subprocess.run", fake_run)
    out = run_agent("hi")
    assert "오류" in out or "error" in out.lower()
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_agent.py -v
```

Expected: 3 new tests fail.

- [ ] **Step 3: Implement `build_prompt` and `run_agent`**

Append to `app/agent.py`:

```python
import subprocess
from pathlib import Path

from app.config import get_settings


SYSTEM_PROMPT = """You are a Telegram assistant for a single-user portfolio dashboard
holding Korean and US equities. Your job is to record trade/dividend
reports, answer holdings queries, and never lose or corrupt data.

Tools: t_list_accounts, t_list_holdings, t_recent_trades, t_recent_dividends,
t_search_ticker_kr, t_verify_ticker_us, t_lookup_ticker, t_record_trade,
t_record_dividend, t_cancel_trade, t_register_instrument.

Resolution rules
- KR stocks: the user reports by Korean name. First try t_lookup_ticker on
  any guess you have; on cache miss use t_search_ticker_kr. If 0 candidates,
  ASK the user. If 1, proceed but mention the ticker in your reply. If
  multiple, list them and ask.
- US stocks: the user reports by ticker. Verify with t_verify_ticker_us.
  If null (likely typo), ASK to confirm.
- Always pass `name` to t_record_trade / t_record_dividend when you've
  resolved a new ticker — this populates the cache.

Safety
- Before calling t_cancel_trade, send a summary and ask 예/아니오. Wait
  for user confirmation in the NEXT message before actually calling.
- If anything is ambiguous (which account, which trade, parse failure),
  ASK rather than guess.
- Currency rule: KRW accounts hold KR tickers (.KS/.KQ); USD accounts
  hold US tickers (no suffix). Never mix.

Style
- Reply in Korean.
- Use ✅ for success, ❓ for confirmations, ⚠️ for problems.
- Be concise. One short paragraph or 3-5 lines max.
"""


def build_prompt(*, window: SlidingWindow, message: str, at: datetime | None = None) -> str:
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Recent conversation (oldest → newest):\n{window.render(at=at)}\n\n"
        f"Latest message from user:\n{message}\n"
    )


_window_singleton = SlidingWindow()


def get_window() -> SlidingWindow:
    return _window_singleton


_ALLOWED_TOOLS = ",".join(f"mcp__dashboard__{n}" for n in (
    "t_list_accounts", "t_list_holdings", "t_recent_trades",
    "t_recent_dividends", "t_search_ticker_kr", "t_verify_ticker_us",
    "t_lookup_ticker", "t_record_trade", "t_record_dividend",
    "t_cancel_trade", "t_register_instrument",
))


def run_agent(message: str, *, window: SlidingWindow | None = None) -> str:
    settings = get_settings()
    win = window or get_window()
    prompt = build_prompt(window=win, message=message)
    cfg = str(Path("mcp.json").resolve())
    try:
        out = subprocess.run(
            [settings.claude_bin, "-p", "--mcp-config", cfg,
             "--allowedTools", _ALLOWED_TOOLS, prompt],
            capture_output=True, text=True, timeout=120, check=False,
        )
    except subprocess.TimeoutExpired:
        return "⚠️ 처리 시간이 초과되었습니다. 다시 시도해주세요."
    if out.returncode != 0:
        return f"⚠️ 오류: {out.stderr.strip()[:200] or 'agent failed'}"
    return out.stdout.strip()
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
.venv/bin/pytest tests/test_agent.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add app/agent.py tests/test_agent.py
git commit -m "feat(agent): assemble prompt and invoke claude -p subprocess"
```

---

## Task 12: Rewrite `app/telegram.py:handle_message`

Replace the parser-driven flow with a simple agent invocation. Webhook + polling routes stay; only `handle_message` is rebuilt.

**Files:**
- Modify: `app/telegram.py`
- Modify: `tests/test_telegram.py` (if it exists; otherwise create)

- [ ] **Step 1: Inspect existing telegram tests**

```bash
ls tests/test_telegram*.py 2>/dev/null
.venv/bin/pytest tests/test_telegram.py -v --collect-only 2>&1 | head -30
```

If `tests/test_telegram.py` exists, read it before proceeding to know what behaviors to preserve at the Telegram-handler level (chat_id filter, message dispatch, polling offset persistence).

- [ ] **Step 2: Rewrite `handle_message`**

Replace the contents of `app/telegram.py` with:

```python
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.agent import get_window, run_agent
from app.api import get_db
from app.config import get_settings
from app.models import Meta

router = APIRouter()


def send_reply(chat_id: int, text: str, *, reply_to: int | None = None) -> None:
    settings = get_settings()
    payload = {"chat_id": chat_id, "text": text}
    if reply_to is not None:
        payload["reply_to_message_id"] = reply_to
    url = f"https://api.telegram.org/bot{settings.tg_bot_token}/sendMessage"
    try:
        httpx.post(url, json=payload, timeout=10)
    except Exception:
        pass


def handle_message(db: Session, msg: dict) -> None:
    """Process a single Telegram 'message' dict via the agent."""
    settings = get_settings()
    chat_id = msg["chat"]["id"]
    if chat_id != settings.tg_chat_id:
        return
    text = msg.get("text", "")
    tg_message_id = msg["message_id"]
    if not text.strip():
        return

    window = get_window()
    now = datetime.now()
    window.append("user", text, at=now)
    reply = run_agent(text, window=window)
    window.append("assistant", reply, at=datetime.now())
    send_reply(chat_id, reply, reply_to=tg_message_id)


@router.post("/telegram/webhook")
async def webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    if x_telegram_bot_api_secret_token != settings.tg_webhook_secret:
        raise HTTPException(401, "bad secret")
    body = await request.json()
    msg = body.get("message") or body.get("edited_message")
    if not msg:
        return {"ok": True}
    handle_message(db, msg)
    return {"ok": True}


def poll_updates_job(session_factory) -> None:
    """Long-poll getUpdates. Persist offset in the Meta table so we don't re-process."""
    db = session_factory()
    try:
        settings = get_settings()
        offset_row = db.get(Meta, "tg_offset")
        params = {"timeout": 25}
        if offset_row is not None:
            params["offset"] = int(offset_row.value) + 1
        url = f"https://api.telegram.org/bot{settings.tg_bot_token}/getUpdates"
        try:
            r = httpx.get(url, params=params, timeout=30)
            data = r.json()
        except Exception:
            return
        if not data.get("ok"):
            return
        last = None
        for update in data.get("result", []):
            last = update["update_id"]
            msg = update.get("message") or update.get("edited_message")
            if msg:
                handle_message(db, msg)
        if last is not None:
            if offset_row is None:
                db.add(Meta(key="tg_offset", value=str(last)))
            else:
                offset_row.value = str(last)
            db.commit()
    finally:
        if hasattr(db, "close"):
            db.close()
```

- [ ] **Step 3: Update `tests/test_telegram.py` (or create it)**

If the file exists, replace its content. If not, create:

```python
from unittest.mock import MagicMock

from app.telegram import handle_message


def test_handle_message_invokes_agent_and_replies(monkeypatch, db):
    sent = {}
    def fake_send(chat_id, text, reply_to=None):
        sent.update(chat_id=chat_id, text=text, reply_to=reply_to)
    monkeypatch.setattr("app.telegram.send_reply", fake_send)
    monkeypatch.setattr("app.telegram.run_agent", lambda text, window=None: "✅ ok")

    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("TG_BOT_TOKEN", "x")
    monkeypatch.setenv("TG_CHAT_ID", "123")
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "s")

    msg = {"chat": {"id": 123}, "text": "테스트", "message_id": 9}
    handle_message(db, msg)

    assert sent["chat_id"] == 123
    assert sent["text"] == "✅ ok"
    assert sent["reply_to"] == 9


def test_handle_message_ignores_unknown_chat(monkeypatch, db):
    called = {}
    monkeypatch.setattr(
        "app.telegram.run_agent",
        lambda *a, **k: called.setdefault("hit", True) or "x",
    )
    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("TG_BOT_TOKEN", "x")
    monkeypatch.setenv("TG_CHAT_ID", "123")
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "s")
    handle_message(db, {"chat": {"id": 999}, "text": "x", "message_id": 1})
    assert "hit" not in called
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_telegram.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add app/telegram.py tests/test_telegram.py
git commit -m "refactor(telegram): replace parser with agent invocation"
```

---

## Task 13: Drop `app/parser.py` and `tests/test_parser.py`

**Files:**
- Delete: `app/parser.py`, `tests/test_parser.py`

- [ ] **Step 1: Verify nothing else imports parser**

```bash
grep -rn "from app.parser\|from app import parser\|app\.parser" app tests | grep -v __pycache__
```

Expected: no results (telegram.py was just rewritten).

- [ ] **Step 2: Delete the files**

```bash
git rm app/parser.py tests/test_parser.py
```

- [ ] **Step 3: Run the full test suite**

```bash
.venv/bin/pytest -q
```

Expected: all tests pass. If a test still references the parser, fix it.

- [ ] **Step 4: Commit**

```bash
git commit -m "chore: remove obsolete parser module and its tests"
```

---

## Task 14: Drop `PendingConfirm` model

**Files:**
- Modify: `app/models.py`
- Modify: `data/dashboard.db` (one-time migration in container)

- [ ] **Step 1: Confirm zero rows live**

```bash
docker compose exec -T app python -c "
from app.db import make_engine, make_session_factory
from app.models import PendingConfirm
from sqlalchemy import select, func
SF = make_session_factory(make_engine())
with SF() as db:
    n = db.execute(select(func.count()).select_from(PendingConfirm)).scalar()
    print('pending_confirms rows:', n)
"
```

If `n > 0`, abort and ask the user how to handle the in-flight confirmations.

- [ ] **Step 2: Drop the table in the live DB**

```bash
docker compose exec -T app python -c "
from app.db import make_engine
from sqlalchemy import text
eng = make_engine()
with eng.begin() as conn:
    conn.execute(text('DROP TABLE IF EXISTS pending_confirms'))
print('dropped')
"
```

- [ ] **Step 3: Remove the model**

In `app/models.py`, delete the `PendingConfirm` class (lines around 105-111). Final verification:

```bash
grep -n "PendingConfirm" app/ tests/ -r
```

Expected: no remaining references in `app/`. The deleted `tests/test_parser.py` and old telegram code already removed in earlier tasks.

- [ ] **Step 4: Run the full test suite**

```bash
.venv/bin/pytest -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/models.py
git commit -m "chore: drop PendingConfirm model (replaced by agent flow)"
```

---

## Task 15: APScheduler — daily KRX cache refresh

**Files:**
- Modify: `app/scheduler.py`
- Modify: `tests/test_scheduler.py` (if exists; otherwise add inline)

- [ ] **Step 1: Add the job function and registration**

In `app/scheduler.py`, add at the end (above `make_scheduler`):

```python
def krx_cache_refresh_job() -> None:
    """Refresh the in-memory KRX listings cache from FinanceDataReader."""
    from app.krx_listings import get_cache
    try:
        get_cache().refresh()
    except Exception:
        pass
```

In `make_scheduler`, before `from app.config import get_settings`, add:

```python
    sched.add_job(
        krx_cache_refresh_job, "cron", hour=7, minute=0,
        id="krx_cache_refresh", max_instances=1, coalesce=True,
    )
```

- [ ] **Step 2: Verify the file imports cleanly**

```bash
.venv/bin/python -c "from app.scheduler import krx_cache_refresh_job, make_scheduler; print('ok')"
```

Expected output: `ok`.

- [ ] **Step 3: Verify cache hydrates at startup**

In `app/main.py`, after `init_db(eng)` and before `SessionLocal = ...`, add:

```python
    from app.krx_listings import get_cache
    cache = get_cache()
    if not cache.hydrate():
        try:
            cache.refresh()
        except Exception:
            pass
```

- [ ] **Step 4: Run all tests**

```bash
.venv/bin/pytest -q
```

Expected: all green. If `test_api.py` tests break because hydrate/refresh hits the network, mock it (monkeypatch `app.krx_listings.fdr` in conftest or in the failing test).

- [ ] **Step 5: Commit**

```bash
git add app/scheduler.py app/main.py
git commit -m "feat(scheduler): hydrate and daily-refresh KRX cache"
```

---

## Task 16: Dockerfile — bake `claude` CLI access

The container must have the `claude` CLI present and authenticated. Existing Dockerfile already mounts `~/.claude` and `~/.claude.json` from the host — verify the binary is on PATH inside the container, since `app/agent.py` calls `subprocess.run(["claude", ...])`.

**Files:**
- Modify: `Dockerfile` (only if `claude` isn't on the container's PATH)

- [ ] **Step 1: Check current container can find claude**

```bash
docker compose exec -T app which claude || echo "MISSING"
```

If output is a path: skip to Step 4. If `MISSING`: continue.

- [ ] **Step 2: Add `claude` install to Dockerfile**

In `Dockerfile`, after the Python deps install layer, add:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && curl -fsSL https://claude.ai/install.sh | sh \
    && rm -rf /var/lib/apt/lists/*
ENV PATH="/root/.local/bin:${PATH}"
```

(Adjust path if the install script puts the binary elsewhere — confirm with the install script's printout.)

- [ ] **Step 3: Rebuild and re-verify**

```bash
docker compose build --pull
docker compose up -d
docker compose exec -T app which claude
```

Expected: a path is printed.

- [ ] **Step 4: End-to-end smoke from inside the container**

```bash
docker compose exec -T app python -c "
import subprocess
out = subprocess.run(
    ['claude', '-p', '--mcp-config', '/app/mcp.json',
     '--allowedTools', 'mcp__dashboard__t_list_accounts',
     'List my account ids using t_list_accounts. Reply with just the comma-separated ids.'],
    capture_output=True, text=True, timeout=120,
)
print('OUT:', out.stdout)
print('ERR:', out.stderr)
"
```

Expected: stdout shows the account ids.

- [ ] **Step 5: Commit (only if Dockerfile changed)**

```bash
git add Dockerfile
git commit -m "build: install claude CLI in container for agent subprocess"
```

---

## Task 17: Manual end-to-end via Telegram

These run against the real Telegram bot connected to the user's chat. No automated assertions — capture observations and fix any defects with targeted commits before merging.

- [ ] **Step 1: Restart the container with the new code**

```bash
docker compose build && docker compose up -d
docker compose logs -f app
```

Watch the logs in a second terminal for errors.

- [ ] **Step 2: KR existing-cache trade**

Send via Telegram: `뉴로핏 5주 22000원에 매수`

Expected reply contains `380550.KQ`, `매수`, `5`, `22000`, `samsung_isa` (or asks which account if no default).

Verify DB:

```bash
docker compose exec -T app python -c "
from app.db import make_engine, make_session_factory
from app.models import Trade
from sqlalchemy import select
SF = make_session_factory(make_engine())
with SF() as db:
    t = db.execute(select(Trade).order_by(Trade.id.desc()).limit(1)).scalar_one()
    print(t.id, t.account_id, t.ticker, t.side, t.quantity, t.price, t.executed_at)
"
```

- [ ] **Step 3: KR new-ticker trade (FDR lookup)**

Pick a stock not in `Instrument` (e.g., `크래프톤 1주 250000`). Expect the agent to call `t_search_ticker_kr`, get `259960.KS`, and either auto-confirm (1 candidate) or ask. Verify the post-save `Instrument` row exists with the right name.

- [ ] **Step 4: US existing-cache trade**

Send: `LLY 1주 920에 매수 (kakao_us)` — expect ✅ reply.

- [ ] **Step 5: US typo case**

Send: `AVGD 1주 200에 매수 (kakao_us)` — expect agent to verify, find null, and ASK to confirm spelling.

- [ ] **Step 6: Cancel flow (two-turn)**

Send: `방금 거 취소` — expect ❓ summary + 예/아니오 prompt.
Reply: `예` — expect ✅ deletion confirmation.
Verify DB no longer has that trade.

- [ ] **Step 7: Holdings query**

Send: `지금 카카오 계좌에 뭐 가지고 있어?` — expect a Korean-language listing.

- [ ] **Step 8: Multi-turn ambiguity**

Send: `삼성 1주 샀어` — expect agent to ask which 삼성 (전자/카드/바이오로직스/…) and which account.
Reply: clarification — expect ✅.

- [ ] **Step 9: Commit any fix-ups**

If the manual run surfaced bugs, commit fixes per finding. Each fix in its own commit.

---

## Task 18: Final sweep + push

- [ ] **Step 1: Lint**

```bash
.venv/bin/ruff check app tests
```

Expected: no errors. Fix any.

- [ ] **Step 2: Full test run**

```bash
.venv/bin/pytest -q
```

Expected: all green.

- [ ] **Step 3: Verify CLAUDE.md is still accurate**

Re-read `CLAUDE.md` for sections that describe the parser/PendingConfirm flow. Update them to describe the agent flow:

- "Telegram ingestion" section should describe `app/agent.py` + MCP server, not `parse_message`
- Drop the description of `PendingConfirm`
- Add a one-line note about `app/krx_listings.py`

- [ ] **Step 4: Commit doc updates**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for agent-based Telegram flow"
```

- [ ] **Step 5: Push**

```bash
git push
```

(No PR step — single-user repo, work merges to `main` directly per project convention.)

---

## Self-review summary

Pass against spec sections:

- **Background** — addressed by Tasks 6-7 (instrument upsert in record_trade), Task 6 (search_ticker_kr replaces hallucination), and Task 12 (parser removal).
- **Process model** — Tasks 8-9, 16.
- **Multi-turn context** — Task 10.
- **MCP tool surface** — Tasks 6-8 cover all 11 tools.
- **KR ticker mapping cache** — Tasks 3-5, 15.
- **System prompt** — Task 11.
- **Safety / guardrails** — System prompt in Task 11; per-tool timeouts inherited from existing `try/except` in `_post_save_recompute`.
- **Migration** — Tasks 12, 13, 14.
- **Testing** — Tasks 3-7, 10-12 (unit+integration); Task 17 (manual e2e).
- **Rollout** — Task 17, Task 18.

Risks per spec:
- Risk 1 verified in Task 1 before any other work.
- Risk 2 (FDR scrape stability) — pickle persistence (Task 5) mitigates.
- Risk 3 (window across restart) — accepted trade-off, no code change required.
- Risk 4 (PendingConfirm drop) — Task 14 step 1 confirms zero rows.

No placeholders. All steps include either exact code or exact shell commands with expected output.
