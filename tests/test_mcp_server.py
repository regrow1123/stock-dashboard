from datetime import date
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.models import (
    Account, Dividend, Instrument, LivePrice, SeedHolding, Trade,
)
from app.mcp_server import (
    list_accounts, list_holdings, recent_trades, recent_dividends,
    search_ticker_kr, verify_ticker_us, lookup_ticker,
    record_trade, record_dividend, cancel_trade, register_instrument,
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


def test_search_ticker_kr_returns_canonical_names_on_substring(monkeypatch):
    from app.krx_listings import KrxCache
    cache = KrxCache()
    cache._load_from_records([
        {"Code": "005930", "Name": "삼성전자", "Market": "KOSPI"},
        {"Code": "207940", "Name": "삼성바이오로직스", "Market": "KOSPI"},
    ])
    monkeypatch.setattr("app.mcp_server.get_cache", lambda: cache)
    out = search_ticker_kr("삼성")
    names = {r["name"] for r in out}
    assert names == {"삼성전자", "삼성바이오로직스"}


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
