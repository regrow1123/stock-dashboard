import argparse
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.benchmarks import BENCHMARK_FOR_CURRENCY, backfill_benchmark
from app.config import get_settings
from app.db import init_db, make_engine, make_session_factory
from app.models import Account, Instrument
from app.prices import backfill_held_prices
from app.sectors import fetch_sector
from app.seed import load_seed
from app.snapshots import recompute_snapshots


def cmd_seed(*, session: Session, seed_path: Path) -> None:
    load_seed(session, seed_path)


def cmd_recompute(*, session: Session, from_date: date, to_date: date) -> None:
    recompute_snapshots(session, from_date=from_date, to_date=to_date)


def cmd_backfill_prices(*, session: Session, from_date: date, to_date: date) -> None:
    backfill_held_prices(session, from_date=from_date, to_date=to_date)
    currencies = {a.currency for a in session.query(Account).all()}
    for currency in currencies:
        bench = BENCHMARK_FOR_CURRENCY.get(currency)
        if bench:
            backfill_benchmark(session, ticker=bench,
                               start=from_date, end=to_date + timedelta(days=1))


def cmd_backfill_sectors(*, session: Session) -> None:
    pending = session.query(Instrument).filter(Instrument.sector.is_(None)).all()
    for inst in pending:
        sector = fetch_sector(inst.ticker)
        if sector:
            inst.sector = sector
    session.commit()


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

    sub.add_parser("backfill-sectors")

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
        elif args.cmd == "backfill-sectors":
            cmd_backfill_sectors(session=session)


if __name__ == "__main__":
    main()
