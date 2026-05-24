from datetime import date

from app.cli import cmd_recompute, cmd_seed
from app.models import Account, SeedHolding


def test_cli_seed_creates_rows(db, tmp_path):
    y = tmp_path / "seed.yaml"
    y.write_text(
        """
accounts:
  - id: a
    name: N
    broker: B
    currency: USD
    holdings:
      - ticker: X
        quantity: 1
        avg_price: 1
""",
        encoding="utf-8",
    )
    cmd_seed(session=db, seed_path=y)
    assert db.query(Account).count() == 1
    assert db.query(SeedHolding).count() == 1


def test_cli_recompute_smoke(db):
    db.add(Account(id="a", name="N", broker="B", currency="USD", display_order=1))
    db.commit()
    # just verify it runs without raising
    cmd_recompute(session=db, from_date=date(2026, 4, 15), to_date=date(2026, 4, 17))


def test_backfill_sectors_fills_only_null(db, monkeypatch):
    from app.cli import cmd_backfill_sectors
    from app.models import Instrument

    db.add_all([
        Instrument(ticker="AAPL", name="Apple", sector=None),
        Instrument(ticker="MSFT", name="Microsoft", sector="정보기술"),
        Instrument(ticker="ZZZ", name="Unknown", sector=None),
    ])
    db.commit()

    # AAPL resolves; ZZZ has no sector and is left untouched.
    lookup = {"AAPL": "정보기술", "ZZZ": None}
    monkeypatch.setattr("app.cli.fetch_sector", lambda t: lookup.get(t))

    cmd_backfill_sectors(session=db)

    assert db.get(Instrument, "AAPL").sector == "정보기술"
    assert db.get(Instrument, "MSFT").sector == "정보기술"  # untouched
    assert db.get(Instrument, "ZZZ").sector is None  # still null, retry later
