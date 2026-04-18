import json
from datetime import date
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Account, PendingConfirm, Trade


def _payload(text: str, message_id: int = 1, chat_id: int = 42):
    return {
        "update_id": 100 + message_id,
        "message": {
            "message_id": message_id,
            "date": 1776487707,
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
            "from": {"id": chat_id, "is_bot": False, "first_name": "u"},
        },
    }


def _install(monkeypatch, engine, chat_id: int = 42, secret: str = "s"):
    monkeypatch.setenv("TG_BOT_TOKEN", "t")
    monkeypatch.setenv("TG_CHAT_ID", str(chat_id))
    monkeypatch.setenv("TG_WEBHOOK_SECRET", secret)
    from app.config import get_settings
    get_settings.cache_clear()
    sent: list[dict] = []
    monkeypatch.setattr(
        "app.telegram.send_reply",
        lambda chat_id, text, **kw: sent.append({"chat_id": chat_id, "text": text}),
    )
    return sent


def test_webhook_rejects_wrong_secret(db, engine, monkeypatch):
    _install(monkeypatch, engine, secret="s")
    app = create_app(engine=engine, start_scheduler=False)
    c = TestClient(app)
    r = c.post("/telegram/webhook", json=_payload("hi"),
               headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"})
    assert r.status_code == 401


def test_high_confidence_trade_is_saved(db, engine, monkeypatch):
    db.add(Account(id="mirae_kr", name="미래에셋 국내", broker="미래에셋",
                   currency="KRW", display_order=1))
    db.commit()
    sent = _install(monkeypatch, engine)

    def fake_parse(message, accounts, today):
        from app.parser import ParseResult
        return ParseResult(
            type="trade", account="mirae_kr", ticker="005930.KS",
            side="buy", quantity=10, price=75000,
            amount=None, executed_at=date(2026, 4, 18), paid_at=None,
            confidence=0.95, note="", raw={},
        )
    monkeypatch.setattr("app.telegram.parse_message", fake_parse)

    app = create_app(engine=engine, start_scheduler=False)
    c = TestClient(app)
    r = c.post("/telegram/webhook", json=_payload("오늘 005930 10주 75000에 매수"),
               headers={"X-Telegram-Bot-Api-Secret-Token": "s"})
    assert r.status_code == 200
    assert db.query(Trade).count() == 1
    assert any("매수" in m["text"] for m in sent)


def test_low_confidence_creates_pending(db, engine, monkeypatch):
    db.add(Account(id="mirae_kr", name="미래에셋 국내", broker="미래에셋",
                   currency="KRW", display_order=1))
    db.commit()
    sent = _install(monkeypatch, engine)

    def fake_parse(message, accounts, today):
        from app.parser import ParseResult
        return ParseResult(
            type="trade", account="mirae_kr", ticker="005930.KS",
            side="buy", quantity=10, price=75000, amount=None,
            executed_at=date(2026, 4, 18), paid_at=None,
            confidence=0.55, note="ambiguous", raw={},
        )
    monkeypatch.setattr("app.telegram.parse_message", fake_parse)

    app = create_app(engine=engine, start_scheduler=False)
    c = TestClient(app)
    c.post("/telegram/webhook", json=_payload("혹시 삼성 샀나"),
           headers={"X-Telegram-Bot-Api-Secret-Token": "s"})
    assert db.query(Trade).count() == 0
    assert db.query(PendingConfirm).count() == 1


def test_high_confidence_trade_null_account_goes_to_pending(db, engine, monkeypatch):
    """High-confidence trade with account=None must route to PendingConfirm, not Trade."""
    db.add(Account(id="mirae_kr", name="미래에셋 국내", broker="미래에셋",
                   currency="KRW", display_order=1))
    db.commit()
    _install(monkeypatch, engine)

    def fake_parse(message, accounts, today):
        from app.parser import ParseResult
        return ParseResult(
            type="trade", account=None, ticker="005930.KS",
            side="buy", quantity=10, price=75000, amount=None,
            executed_at=date(2026, 4, 18), paid_at=None,
            confidence=0.95, note="", raw={},
        )
    monkeypatch.setattr("app.telegram.parse_message", fake_parse)

    app = create_app(engine=engine, start_scheduler=False)
    c = TestClient(app)
    r = c.post("/telegram/webhook", json=_payload("삼성 10주 75000 매수"),
               headers={"X-Telegram-Bot-Api-Secret-Token": "s"})
    assert r.status_code == 200
    assert db.query(Trade).count() == 0
    assert db.query(PendingConfirm).count() == 1
