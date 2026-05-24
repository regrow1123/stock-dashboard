from datetime import date, datetime

from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Account, LivePrice, SeedHolding


def _seed_two_accounts(db):
    db.add_all([
        Account(id="mirae_kr", name="미래에셋 국내", broker="미래에셋",
                currency="KRW", display_order=1),
        Account(id="ibkr_us", name="IBKR 미국", broker="IBKR",
                currency="USD", display_order=2),
        SeedHolding(account_id="mirae_kr", ticker="005930.KS",
                    quantity=10, avg_price=70000),
        SeedHolding(account_id="ibkr_us", ticker="AAPL",
                    quantity=5, avg_price=170),
    ])
    db.add_all([
        LivePrice(ticker="005930.KS", price=75000, currency="KRW",
                  fetched_at=datetime(2026, 4, 18, 9, 30)),
        LivePrice(ticker="AAPL", price=180, currency="USD",
                  fetched_at=datetime(2026, 4, 18, 9, 30)),
    ])
    db.commit()


def _app_with_engine(engine, monkeypatch):
    monkeypatch.setenv("TG_BOT_TOKEN", "t")
    monkeypatch.setenv("TG_CHAT_ID", "1")
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "s")
    from app.config import get_settings
    get_settings.cache_clear()
    return create_app(engine=engine, start_scheduler=False)


def test_accounts_endpoint(db, engine, monkeypatch):
    _seed_two_accounts(db)
    app = _app_with_engine(engine, monkeypatch)
    c = TestClient(app)
    r = c.get("/api/accounts")
    assert r.status_code == 200
    payload = r.json()
    assert [a["id"] for a in payload] == ["mirae_kr", "ibkr_us"]


def test_holdings_endpoint_uses_live_price(db, engine, monkeypatch):
    _seed_two_accounts(db)
    app = _app_with_engine(engine, monkeypatch)
    c = TestClient(app)
    r = c.get("/api/accounts/mirae_kr/holdings")
    assert r.status_code == 200
    rows = r.json()
    assert rows[0]["ticker"] == "005930.KS"
    assert rows[0]["quantity"] == 10
    assert rows[0]["current_price"] == 75000
    assert rows[0]["value"] == 10 * 75000
    assert rows[0]["cost"] == 10 * 70000


def test_summary_endpoint_groups_by_currency(db, engine, monkeypatch):
    _seed_two_accounts(db)
    app = _app_with_engine(engine, monkeypatch)
    c = TestClient(app)
    r = c.get("/api/summary")
    assert r.status_code == 200
    payload = r.json()
    currencies = {row["currency"]: row for row in payload["totals"]}
    assert currencies["KRW"]["value"] == 10 * 75000
    assert currencies["USD"]["value"] == 5 * 180


def test_realized_endpoint(db, engine, monkeypatch):
    from datetime import date
    from app.models import Account, Trade
    db.add(Account(id="a", name="N", broker="B", currency="USD", display_order=1))
    db.add_all([
        Trade(account_id="a", ticker="X", side="buy", quantity=10, price=100,
              executed_at=date(2026, 1, 1)),
        Trade(account_id="a", ticker="X", side="sell", quantity=4, price=150,
              executed_at=date(2026, 1, 2)),
    ])
    db.commit()
    app = _app_with_engine(engine, monkeypatch)
    c = TestClient(app)
    r = c.get("/api/accounts/a/realized")
    assert r.status_code == 200
    data = r.json()
    assert data["realized"] == 200.0  # 4*(150-100)


def test_post_sells_endpoint(db, engine, monkeypatch):
    from datetime import timedelta
    from app.models import Account, Instrument, LivePrice, Trade
    today = date.today()
    db.add_all([
        Account(id="a", name="ISA", broker="B", currency="KRW", display_order=1),
        Account(id="b", name="US", broker="B", currency="USD", display_order=2),
        Instrument(ticker="005930.KS", name="삼성전자"),
    ])
    db.add_all([
        # Account a, ticker X — older sell that should be filtered out (>90d)
        Trade(account_id="a", ticker="005930.KS", side="sell", quantity=2,
              price=60000, executed_at=today - timedelta(days=200)),
        # Account a, ticker X — most recent sell within window
        Trade(account_id="a", ticker="005930.KS", side="sell", quantity=3,
              price=70000, executed_at=today - timedelta(days=30)),
        # Account a, ticker X — earlier sell within window (should be hidden, dup)
        Trade(account_id="a", ticker="005930.KS", side="sell", quantity=1,
              price=65000, executed_at=today - timedelta(days=60)),
        # Account a, ticker Y — only sell, within window
        Trade(account_id="a", ticker="000660.KS", side="sell", quantity=4,
              price=200000, executed_at=today - timedelta(days=10)),
        # Account a — buy should be ignored
        Trade(account_id="a", ticker="005930.KS", side="buy", quantity=10,
              price=50000, executed_at=today - timedelta(days=5)),
        # Account b, ticker AAPL — within window
        Trade(account_id="b", ticker="AAPL", side="sell", quantity=2,
              price=200, executed_at=today - timedelta(days=20)),
    ])
    db.add_all([
        LivePrice(ticker="005930.KS", price=84000, currency="KRW",
                  fetched_at=datetime(2026, 4, 18, 9, 30)),
        LivePrice(ticker="000660.KS", price=180000, currency="KRW",
                  fetched_at=datetime(2026, 4, 18, 9, 30)),
        LivePrice(ticker="AAPL", price=240, currency="USD",
                  fetched_at=datetime(2026, 4, 18, 9, 30)),
    ])
    db.commit()
    app = _app_with_engine(engine, monkeypatch)
    c = TestClient(app)
    # Account a: two sold tickers, older 005930 sell deduped to most recent
    ra = c.get("/api/accounts/a/post_sells")
    assert ra.status_code == 200
    payload_a = ra.json()
    assert payload_a["currency"] == "KRW"
    a_items = {it["ticker"]: it for it in payload_a["items"]}
    assert set(a_items.keys()) == {"005930.KS", "000660.KS"}
    s = a_items["005930.KS"]
    assert s["sold_price"] == 70000
    assert s["current_price"] == 84000
    assert round(s["return_pct"], 4) == round((84000 - 70000) / 70000, 4)
    assert s["name"] == "삼성전자"
    # Negative return case
    h = a_items["000660.KS"]
    assert h["return_pct"] < 0
    # Sorted desc by return_pct within an account
    a_returns = [it["return_pct"] for it in payload_a["items"]]
    assert a_returns == sorted(a_returns, reverse=True)
    # Account b
    rb = c.get("/api/accounts/b/post_sells")
    assert rb.status_code == 200
    b_items = rb.json()["items"]
    assert len(b_items) == 1
    assert b_items[0]["ticker"] == "AAPL"
    # Unknown account → 404
    assert c.get("/api/accounts/no_such/post_sells").status_code == 404


def test_post_sells_handles_missing_live_price(db, engine, monkeypatch):
    from datetime import timedelta
    from app.models import Account, Trade
    today = date.today()
    db.add(Account(id="a", name="N", broker="B", currency="USD", display_order=1))
    db.add(Trade(account_id="a", ticker="ZZZ", side="sell", quantity=1,
                 price=50, executed_at=today - timedelta(days=10)))
    db.commit()
    app = _app_with_engine(engine, monkeypatch)
    c = TestClient(app)
    items = c.get("/api/accounts/a/post_sells").json()["items"]
    assert items[0]["current_price"] is None
    assert items[0]["return_pct"] is None
