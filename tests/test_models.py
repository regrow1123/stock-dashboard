from datetime import date, datetime

from app.models import Account, Trade


def test_account_and_trade(db):
    acc = Account(
        id="mirae_kr",
        name="미래에셋 국내",
        broker="미래에셋",
        currency="KRW",
        display_order=1,
    )
    db.add(acc)
    db.commit()

    t = Trade(
        account_id="mirae_kr",
        ticker="005930.KS",
        side="buy",
        quantity=10,
        price=75000.0,
        executed_at=date(2026, 4, 18),
        raw_text="삼성 10주 75000 매수",
        tg_message_id=1,
        created_at=datetime(2026, 4, 18, 9, 0, 0),
    )
    db.add(t)
    db.commit()

    assert db.query(Trade).count() == 1
    assert db.query(Account).first().currency == "KRW"
