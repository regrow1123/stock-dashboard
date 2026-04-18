from datetime import date, datetime
from unittest.mock import MagicMock

import pandas as pd

from app.models import LivePrice, Price
from app.prices import backfill_prices, refresh_live_prices


def _fake_history_df(dates, closes):
    idx = pd.to_datetime(dates)
    return pd.DataFrame({"Close": closes}, index=idx)


def test_backfill_inserts_daily_closes(db, monkeypatch):
    def fake_download(ticker, start, end, progress=False, auto_adjust=False):
        return _fake_history_df(
            ["2026-04-16", "2026-04-17"], [100.0, 101.0]
        )

    fake_yf = MagicMock()
    fake_yf.download.side_effect = fake_download
    monkeypatch.setattr("app.prices.yf", fake_yf)

    backfill_prices(db, ticker="AAPL", currency="USD",
                    start=date(2026, 4, 16), end=date(2026, 4, 18))
    rows = db.query(Price).order_by(Price.date).all()
    assert [r.date for r in rows] == [date(2026, 4, 16), date(2026, 4, 17)]
    assert rows[0].close == 100.0
    assert rows[0].currency == "USD"


def test_refresh_live_stores_latest_price(db, monkeypatch):
    fake_ticker = MagicMock()
    fake_ticker.fast_info = {"last_price": 150.25, "currency": "USD"}
    fake_yf = MagicMock()
    fake_yf.Ticker.return_value = fake_ticker
    monkeypatch.setattr("app.prices.yf", fake_yf)

    refresh_live_prices(db, tickers=["AAPL"], now=datetime(2026, 4, 18, 9, 30))
    lp = db.get(LivePrice, "AAPL")
    assert lp.price == 150.25
    assert lp.currency == "USD"
