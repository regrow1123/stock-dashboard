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


def test_handle_message_skips_foreign_chat(db, monkeypatch):
    from app.telegram import handle_message
    monkeypatch.setenv("TG_BOT_TOKEN", "t")
    monkeypatch.setenv("TG_CHAT_ID", "42")
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "s")
    from app.config import get_settings
    get_settings.cache_clear()
    sent = []
    monkeypatch.setattr("app.telegram.send_reply",
                        lambda chat_id, text, **kw: sent.append(text))

    handle_message(db, {
        "message_id": 1, "text": "hi",
        "chat": {"id": 999, "type": "private"},
    })
    from app.models import Trade
    assert db.query(Trade).count() == 0
    assert sent == []


def test_polling_processes_new_update_and_stores_offset(db, monkeypatch):
    from app.models import Account, Meta, Trade
    from app.telegram import poll_updates_job
    db.add(Account(id="a", name="N", broker="B", currency="USD", display_order=1))
    db.commit()

    monkeypatch.setenv("TG_BOT_TOKEN", "t")
    monkeypatch.setenv("TG_CHAT_ID", "42")
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "s")
    from app.config import get_settings
    get_settings.cache_clear()

    def fake_get(url, params=None, timeout=None):
        class R:
            def json(self):
                return {
                    "ok": True,
                    "result": [
                        {"update_id": 77,
                         "message": {
                             "message_id": 1, "text": "x",
                             "chat": {"id": 42, "type": "private"},
                         }},
                    ],
                }
        return R()
    monkeypatch.setattr("app.telegram.httpx.get", fake_get)

    from datetime import date
    from app.parser import ParseResult
    def fake_parse(message, accounts, today):
        return ParseResult(
            type="trade", account="a", ticker="X", side="buy",
            quantity=1, price=1, amount=None,
            executed_at=date(2026, 4, 18), paid_at=None,
            confidence=0.95, note="", raw={},
        )
    monkeypatch.setattr("app.telegram.parse_message", fake_parse)
    monkeypatch.setattr("app.telegram.send_reply",
                        lambda *a, **kw: None)

    poll_updates_job(session_factory=lambda: db)
    assert db.query(Trade).count() == 1
    assert db.get(Meta, "tg_offset").value == "77"


def test_cancel_intent_deletes_latest_trade_after_confirm(db, engine, monkeypatch):
    db.add(Account(id="kakao_us", name="카카오 종합", broker="카카오",
                   currency="USD", display_order=1))
    db.add(Trade(account_id="kakao_us", ticker="AAPL", side="buy",
                 quantity=5, price=190, executed_at=date(2026, 4, 24),
                 raw_text="prev", tg_message_id=10))
    db.commit()
    sent = _install(monkeypatch, engine)

    def fake_parse(message, accounts, today):
        from app.parser import ParseResult
        return ParseResult(
            type="cancel", account=None, ticker=None, side=None,
            quantity=None, price=None, amount=None,
            executed_at=None, paid_at=None,
            confidence=0.97, note="cancel", raw={},
        )
    monkeypatch.setattr("app.telegram.parse_message", fake_parse)

    app = create_app(engine=engine, start_scheduler=False)
    c = TestClient(app)
    c.post("/telegram/webhook", json=_payload("방금 보낸 메시지 취소해줘", message_id=11),
           headers={"X-Telegram-Bot-Api-Secret-Token": "s"})
    assert db.query(PendingConfirm).count() == 1
    assert db.query(Trade).count() == 1  # not yet deleted
    assert any("취소할까요" in m["text"] for m in sent)

    c.post("/telegram/webhook", json=_payload("예", message_id=12),
           headers={"X-Telegram-Bot-Api-Secret-Token": "s"})
    assert db.query(Trade).count() == 0
    assert db.query(PendingConfirm).count() == 0
    assert any("삭제" in m["text"] for m in sent)


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
