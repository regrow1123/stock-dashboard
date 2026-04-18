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
