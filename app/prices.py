from datetime import date, datetime, timedelta
from typing import Iterable

import yfinance as yf
from sqlalchemy.orm import Session

from app.models import LivePrice, Price


def backfill_prices(
    db: Session, *, ticker: str, currency: str, start: date, end: date
) -> int:
    """Download daily closes [start, end) inclusive start, exclusive end — upsert Price rows."""
    df = yf.download(
        ticker, start=start.isoformat(), end=end.isoformat(), progress=False, auto_adjust=False
    )
    if df is None or df.empty:
        return 0
    n = 0
    existing = {
        r.date: r
        for r in db.query(Price).filter(
            Price.ticker == ticker, Price.date >= start, Price.date < end
        ).all()
    }
    for ts, row in df.iterrows():
        d = ts.date() if hasattr(ts, "date") else ts
        close = float(row["Close"])
        r = existing.get(d)
        if r is None:
            r = Price(ticker=ticker, date=d, close=close, currency=currency)
            db.add(r)
        else:
            r.close = close
            r.currency = currency
        n += 1
    db.commit()
    return n


def refresh_live_prices(
    db: Session, *, tickers: Iterable[str], now: datetime | None = None
) -> int:
    ts = now or datetime.utcnow()
    n = 0
    for t in tickers:
        try:
            info = yf.Ticker(t).fast_info
            price = float(info["last_price"])
            currency = str(info.get("currency") or "")
        except Exception:
            continue
        row = db.get(LivePrice, t)
        if row is None:
            row = LivePrice(ticker=t, price=price, currency=currency, fetched_at=ts)
            db.add(row)
        else:
            row.price = price
            row.currency = currency
            row.fetched_at = ts
        n += 1
    db.commit()
    return n


def close_on_or_before(db: Session, ticker: str, d: date) -> float | None:
    row = (
        db.query(Price)
        .filter(Price.ticker == ticker, Price.date <= d)
        .order_by(Price.date.desc())
        .first()
    )
    return float(row.close) if row else None
