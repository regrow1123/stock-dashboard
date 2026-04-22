from datetime import date, datetime, timedelta
from typing import Iterable

import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session

from app.models import Account, LivePrice, Price, SeedHolding, Trade


def _close_series(df: "pd.DataFrame", ticker: str) -> "pd.Series":
    """Handle both flat and multi-indexed yfinance frames."""
    col = df["Close"]
    if isinstance(col, pd.DataFrame):
        return col[ticker] if ticker in col.columns else col.iloc[:, 0]
    return col


def backfill_prices(
    db: Session, *, ticker: str, currency: str, start: date, end: date
) -> int:
    """Download daily closes [start, end) inclusive start, exclusive end — upsert Price rows."""
    df = yf.download(
        ticker, start=start.isoformat(), end=end.isoformat(), progress=False, auto_adjust=False
    )
    if df is None or df.empty:
        return 0
    closes = _close_series(df, ticker)
    n = 0
    existing = {
        r.date: r
        for r in db.query(Price).filter(
            Price.ticker == ticker, Price.date >= start, Price.date < end
        ).all()
    }
    for ts, close_val in closes.items():
        if pd.isna(close_val):
            continue
        d = ts.date() if hasattr(ts, "date") else ts
        close = float(close_val)
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


def backfill_held_prices(
    session: Session, *, from_date: date, to_date: date
) -> None:
    tickers_by_currency: dict[str, set[str]] = {}
    for sh in session.query(SeedHolding).all():
        acc = session.get(Account, sh.account_id)
        tickers_by_currency.setdefault(acc.currency, set()).add(sh.ticker)
    for t in session.query(Trade).all():
        acc = session.get(Account, t.account_id)
        tickers_by_currency.setdefault(acc.currency, set()).add(t.ticker)
    end_exclusive = to_date + timedelta(days=1)
    for currency, tickers in tickers_by_currency.items():
        for tk in tickers:
            backfill_prices(
                session, ticker=tk, currency=currency,
                start=from_date, end=end_exclusive,
            )


def close_on_or_before(db: Session, ticker: str, d: date) -> float | None:
    row = (
        db.query(Price)
        .filter(Price.ticker == ticker, Price.date <= d)
        .order_by(Price.date.desc())
        .first()
    )
    return float(row.close) if row else None
