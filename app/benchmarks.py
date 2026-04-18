from datetime import date

import yfinance as yf
from sqlalchemy.orm import Session

from app.models import Benchmark


def backfill_benchmark(db: Session, *, ticker: str, start: date, end: date) -> int:
    df = yf.download(
        ticker, start=start.isoformat(), end=end.isoformat(),
        progress=False, auto_adjust=False,
    )
    if df is None or df.empty:
        return 0
    existing = {
        r.date: r
        for r in db.query(Benchmark).filter(
            Benchmark.ticker == ticker, Benchmark.date >= start, Benchmark.date < end
        ).all()
    }
    n = 0
    for ts, row in df.iterrows():
        d = ts.date() if hasattr(ts, "date") else ts
        close = float(row["Close"])
        r = existing.get(d)
        if r is None:
            db.add(Benchmark(ticker=ticker, date=d, close=close))
        else:
            r.close = close
        n += 1
    db.commit()
    return n


def rebase_series(points: list[tuple[date, float]]) -> list[tuple[date, float]]:
    if not points:
        return []
    base = points[0][1]
    if base == 0:
        return [(d, 0.0) for d, _ in points]
    return [(d, v / base) for d, v in points]


BENCHMARK_FOR_CURRENCY = {"KRW": "^KS11", "USD": "^GSPC"}
