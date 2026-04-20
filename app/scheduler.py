from datetime import date, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.benchmarks import BENCHMARK_FOR_CURRENCY, backfill_benchmark
from app.models import Account, SeedHolding, Trade
from app.prices import refresh_live_prices
from app.snapshots import recompute_snapshots


def _active_tickers(db: Session) -> list[str]:
    seeds = [s.ticker for s in db.query(SeedHolding).all()]
    trades = [t.ticker for t in db.query(Trade).all()]
    return sorted(set(seeds + trades))


def refresh_prices_job(session_factory) -> None:
    db: Session = session_factory()
    try:
        tickers = _active_tickers(db)
        refresh_live_prices(db, tickers=tickers)
    finally:
        if hasattr(db, "close"):
            db.close()


def daily_snapshot_job(session_factory, *, now: datetime | None = None) -> None:
    db: Session = session_factory()
    try:
        today = (now or datetime.now()).date()
        recompute_snapshots(db, from_date=today - timedelta(days=7), to_date=today)
    finally:
        if hasattr(db, "close"):
            db.close()


def benchmarks_job(session_factory) -> None:
    db: Session = session_factory()
    try:
        today = date.today()
        start = today - timedelta(days=400)
        from app.api import MARKET_TICKERS
        tickers = {BENCHMARK_FOR_CURRENCY.get(a.currency) for a in db.query(Account).all()}
        tickers.discard(None)
        tickers |= {tk for tk, _ in MARKET_TICKERS}
        for tk in tickers:
            backfill_benchmark(db, ticker=tk, start=start, end=today + timedelta(days=1))
    finally:
        if hasattr(db, "close"):
            db.close()


def make_scheduler(session_factory) -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone="Asia/Seoul")
    sched.add_job(refresh_prices_job, "interval", minutes=15, args=[session_factory],
                  id="refresh_prices", max_instances=1)
    sched.add_job(daily_snapshot_job, "cron", hour=23, minute=30, args=[session_factory],
                  id="daily_snapshot", max_instances=1)
    sched.add_job(benchmarks_job, "cron", hour=23, minute=45, args=[session_factory],
                  id="benchmarks", max_instances=1)
    from app.config import get_settings
    from app.telegram import poll_updates_job
    if get_settings().tg_polling:
        sched.add_job(
            poll_updates_job, "interval", seconds=30, args=[session_factory],
            id="poll_telegram", max_instances=1, coalesce=True,
        )
    return sched
