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
