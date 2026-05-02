from datetime import date, datetime

from app.models import Account, Price, SeedHolding
from app.scheduler import benchmarks_job, daily_snapshot_job, refresh_prices_job


def test_refresh_prices_job_calls_refresh(db, monkeypatch):
    db.add(Account(id="a", name="N", broker="B", currency="USD", display_order=1))
    db.add(SeedHolding(account_id="a", ticker="AAPL", quantity=1, avg_price=1))
    db.commit()
    called = {}

    def fake_refresh(session, *, tickers, now=None):
        called["tickers"] = list(tickers)
        return len(called["tickers"])
    monkeypatch.setattr("app.scheduler.refresh_live_prices", fake_refresh)

    refresh_prices_job(session_factory=lambda: db)
    assert called["tickers"] == ["AAPL"]


def test_daily_snapshot_job_recomputes_last_7d(db, monkeypatch):
    db.add(Account(id="a", name="N", broker="B", currency="USD", display_order=1))
    db.add(SeedHolding(account_id="a", ticker="X", quantity=1, avg_price=1))
    db.add(Price(ticker="X", date=date(2026, 4, 18), close=100, currency="USD"))
    db.commit()
    calls = []

    def fake_recompute(session, *, from_date, to_date, account_id=None):
        calls.append((from_date, to_date))
        return 0
    monkeypatch.setattr("app.scheduler.recompute_snapshots", fake_recompute)

    daily_snapshot_job(session_factory=lambda: db,
                       now=datetime(2026, 4, 18, 23, 30))
    assert calls[0][1] == date(2026, 4, 18)
    assert (calls[0][1] - calls[0][0]).days == 7


def test_benchmarks_job_includes_skew(db, monkeypatch):
    db.add(Account(id="a", name="N", broker="B", currency="USD", display_order=1))
    db.commit()
    called: list[str] = []

    def fake_backfill(session, *, ticker, start, end):
        called.append(ticker)
        return 0
    monkeypatch.setattr("app.scheduler.backfill_benchmark", fake_backfill)

    benchmarks_job(session_factory=lambda: db)
    assert "^SKEW" in called
