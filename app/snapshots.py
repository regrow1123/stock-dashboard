from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import Account, Price, SeedHolding, Snapshot, Trade
from app.prices import close_on_or_before


def _iter_dates(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _quantities_on(
    db: Session, account_id: str, tickers: set[str], on_date: date
) -> dict[str, float]:
    q: dict[str, float] = defaultdict(float)
    for sh in db.query(SeedHolding).filter_by(account_id=account_id).all():
        q[sh.ticker] += sh.quantity
        tickers.add(sh.ticker)
    trades = (
        db.query(Trade)
        .filter(Trade.account_id == account_id, Trade.executed_at <= on_date)
        .all()
    )
    for t in trades:
        tickers.add(t.ticker)
        sign = 1 if t.side == "buy" else -1
        q[t.ticker] += sign * t.quantity
    return q


def recompute_snapshots(
    db: Session, *, from_date: date, to_date: date, account_id: str | None = None
) -> int:
    """Recompute snapshots(date in [from_date, to_date]) for the given account (or all)."""
    accounts = (
        db.query(Account).filter(Account.id == account_id).all()
        if account_id
        else db.query(Account).all()
    )
    total = 0
    for acc in accounts:
        db.query(Snapshot).filter(
            Snapshot.account_id == acc.id,
            Snapshot.date >= from_date,
            Snapshot.date <= to_date,
        ).delete(synchronize_session=False)
        db.commit()

        for d in _iter_dates(from_date, to_date):
            tickers: set[str] = set()
            qty_map = _quantities_on(db, acc.id, tickers, d)
            for ticker in tickers:
                q = qty_map.get(ticker, 0.0)
                if q <= 0:
                    continue
                close = close_on_or_before(db, ticker, d)
                if close is None:
                    continue
                db.add(
                    Snapshot(
                        date=d,
                        account_id=acc.id,
                        ticker=ticker,
                        quantity=q,
                        close=close,
                        value=q * close,
                    )
                )
                total += 1
        db.commit()
    return total
