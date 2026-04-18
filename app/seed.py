from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app.models import Account, SeedHolding


def load_seed(db: Session, path: Path) -> None:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    for a in data.get("accounts", []):
        acc = db.get(Account, a["id"])
        if acc is None:
            acc = Account(id=a["id"])
            db.add(acc)
        acc.name = a["name"]
        acc.broker = a["broker"]
        acc.currency = a["currency"]
        acc.display_order = a.get("display_order", 0)

        existing = {h.ticker: h for h in db.query(SeedHolding).filter_by(account_id=a["id"]).all()}
        for h in a.get("holdings", []):
            row = existing.get(h["ticker"])
            if row is None:
                row = SeedHolding(account_id=a["id"], ticker=h["ticker"])
                db.add(row)
            row.quantity = float(h["quantity"])
            row.avg_price = float(h["avg_price"])
    db.commit()
