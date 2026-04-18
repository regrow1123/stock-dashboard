from app.models import Account, SeedHolding
from app.seed import load_seed


def test_load_seed_creates_accounts_and_holdings(db, tmp_path):
    y = tmp_path / "s.yaml"
    y.write_text(
        """
accounts:
  - id: a1
    name: N1
    broker: B
    currency: KRW
    display_order: 1
    holdings:
      - ticker: 005930.KS
        quantity: 10
        avg_price: 70000
""",
        encoding="utf-8",
    )
    load_seed(db, y)
    assert db.query(Account).count() == 1
    h = db.query(SeedHolding).one()
    assert h.ticker == "005930.KS"
    assert h.quantity == 10
    assert h.avg_price == 70000


def test_load_seed_is_idempotent(db, tmp_path):
    y = tmp_path / "s.yaml"
    y.write_text(
        """
accounts:
  - id: a1
    name: N1
    broker: B
    currency: KRW
    holdings:
      - ticker: T
        quantity: 1
        avg_price: 1
""",
        encoding="utf-8",
    )
    load_seed(db, y)
    load_seed(db, y)  # second call should not duplicate
    assert db.query(Account).count() == 1
    assert db.query(SeedHolding).count() == 1
