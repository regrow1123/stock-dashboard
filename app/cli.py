import argparse
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.benchmarks import BENCHMARK_FOR_CURRENCY, backfill_benchmark
from app.config import get_settings
from app.db import init_db, make_engine, make_session_factory
from app.models import Account, SeedHolding, Trade
from app.prices import backfill_prices
from app.seed import load_seed
from app.snapshots import recompute_snapshots


def cmd_seed(*, session: Session, seed_path: Path) -> None:
    load_seed(session, seed_path)


def cmd_recompute(*, session: Session, from_date: date, to_date: date) -> None:
    recompute_snapshots(session, from_date=from_date, to_date=to_date)


def cmd_backfill_prices(*, session: Session, from_date: date, to_date: date) -> None:
    tickers_by_currency: dict[str, set[str]] = {}
    for sh in session.query(SeedHolding).all():
        acc = session.get(Account, sh.account_id)
        tickers_by_currency.setdefault(acc.currency, set()).add(sh.ticker)
    for t in session.query(Trade).all():
        acc = session.get(Account, t.account_id)
        tickers_by_currency.setdefault(acc.currency, set()).add(t.ticker)
    for currency, tickers in tickers_by_currency.items():
        for tk in tickers:
            backfill_prices(session, ticker=tk, currency=currency,
                            start=from_date, end=to_date + timedelta(days=1))
        bench = BENCHMARK_FOR_CURRENCY.get(currency)
        if bench:
            backfill_benchmark(session, ticker=bench,
                               start=from_date, end=to_date + timedelta(days=1))


def _today() -> date:
    return date.today()


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_seed = sub.add_parser("seed")
    p_seed.add_argument("--path", type=Path, default=None)

    p_rec = sub.add_parser("recompute")
    p_rec.add_argument("--from", dest="from_date", type=date.fromisoformat, required=True)
    p_rec.add_argument("--to", dest="to_date", type=date.fromisoformat, default=None)

    p_bp = sub.add_parser("backfill-prices")
    p_bp.add_argument("--from", dest="from_date", type=date.fromisoformat, required=True)
    p_bp.add_argument("--to", dest="to_date", type=date.fromisoformat, default=None)

    args = parser.parse_args()
    settings = get_settings()
    engine = make_engine()
    init_db(engine)
    SessionLocal = make_session_factory(engine)
    with SessionLocal() as session:
        if args.cmd == "seed":
            cmd_seed(session=session, seed_path=args.path or settings.seed_path)
        elif args.cmd == "recompute":
            cmd_recompute(session=session, from_date=args.from_date,
                          to_date=args.to_date or _today())
        elif args.cmd == "backfill-prices":
            cmd_backfill_prices(session=session, from_date=args.from_date,
                                to_date=args.to_date or _today())


if __name__ == "__main__":
    main()
