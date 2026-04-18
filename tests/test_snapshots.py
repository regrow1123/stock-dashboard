from datetime import date

from app.models import Account, Price, SeedHolding, Snapshot, Trade
from app.snapshots import recompute_snapshots


def _setup(db):
    db.add(Account(id="a", name="N", broker="B", currency="USD", display_order=1))
    db.add(SeedHolding(account_id="a", ticker="X", quantity=10, avg_price=100))
    db.add_all([
        Price(ticker="X", date=date(2026, 4, 15), close=110, currency="USD"),
        Price(ticker="X", date=date(2026, 4, 16), close=120, currency="USD"),
        Price(ticker="X", date=date(2026, 4, 17), close=125, currency="USD"),
    ])
    db.commit()


def test_recompute_with_only_seed(db):
    _setup(db)
    recompute_snapshots(db, from_date=date(2026, 4, 15), to_date=date(2026, 4, 17))
    snaps = db.query(Snapshot).order_by(Snapshot.date).all()
    assert [s.date for s in snaps] == [
        date(2026, 4, 15), date(2026, 4, 16), date(2026, 4, 17),
    ]
    assert snaps[-1].quantity == 10
    assert snaps[-1].value == 10 * 125


def test_recompute_with_mid_period_buy(db):
    _setup(db)
    db.add(Trade(account_id="a", ticker="X", side="buy", quantity=5, price=115,
                 executed_at=date(2026, 4, 16)))
    db.commit()
    recompute_snapshots(db, from_date=date(2026, 4, 15), to_date=date(2026, 4, 17))
    snaps = db.query(Snapshot).order_by(Snapshot.date).all()
    assert snaps[0].quantity == 10   # 4/15: only seed
    assert snaps[1].quantity == 15   # 4/16: +5
    assert snaps[2].quantity == 15
    assert snaps[2].value == 15 * 125


def test_late_reported_trade_updates_old_snapshots(db):
    _setup(db)
    recompute_snapshots(db, from_date=date(2026, 4, 15), to_date=date(2026, 4, 17))
    # later, user reports a trade that happened on 4/16
    db.add(Trade(account_id="a", ticker="X", side="buy", quantity=7, price=118,
                 executed_at=date(2026, 4, 16)))
    db.commit()
    recompute_snapshots(db, from_date=date(2026, 4, 16), to_date=date(2026, 4, 17))
    snaps = db.query(Snapshot).order_by(Snapshot.date).all()
    q_by_date = {s.date: s.quantity for s in snaps}
    assert q_by_date[date(2026, 4, 15)] == 10
    assert q_by_date[date(2026, 4, 16)] == 17
    assert q_by_date[date(2026, 4, 17)] == 17
