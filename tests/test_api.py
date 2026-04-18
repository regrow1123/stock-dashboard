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
    return create_app(engine=engine)


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


def test_benchmark_endpoint_rebased(db, engine, monkeypatch):
    from datetime import date
    from app.models import Account, Benchmark, SeedHolding, Snapshot
    db.add(Account(id="a", name="N", broker="B", currency="USD", display_order=1))
    db.add(SeedHolding(account_id="a", ticker="X", quantity=10, avg_price=100))
    db.add_all([
        Snapshot(date=date(2026, 4, 15), account_id="a", ticker="X",
                 quantity=10, close=100, value=1000),
        Snapshot(date=date(2026, 4, 16), account_id="a", ticker="X",
                 quantity=10, close=110, value=1100),
        Benchmark(ticker="^GSPC", date=date(2026, 4, 15), close=5000),
        Benchmark(ticker="^GSPC", date=date(2026, 4, 16), close=5100),
    ])
    db.commit()
    app = _app_with_engine(engine, monkeypatch)
    c = TestClient(app)
    r = c.get("/api/accounts/a/benchmark")
    assert r.status_code == 200
    data = r.json()
    assert data["portfolio"][0]["value"] == 1.0
    assert data["benchmark"][0]["value"] == 1.0
    assert round(data["portfolio"][1]["value"], 3) == 1.1
    assert round(data["benchmark"][1]["value"], 3) == 1.02
