from app.telegram import handle_message


def test_handle_message_invokes_agent_and_replies(monkeypatch, db):
    sent = {}
    def fake_send(chat_id, text, reply_to=None):
        sent.update(chat_id=chat_id, text=text, reply_to=reply_to)
    monkeypatch.setattr("app.telegram.send_reply", fake_send)
    monkeypatch.setattr("app.telegram.run_agent", lambda text, window=None: "✅ ok")

    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("TG_BOT_TOKEN", "x")
    monkeypatch.setenv("TG_CHAT_ID", "123")
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "s")

    msg = {"chat": {"id": 123}, "text": "테스트", "message_id": 9}
    handle_message(db, msg)

    assert sent["chat_id"] == 123
    assert sent["text"] == "✅ ok"
    assert sent["reply_to"] == 9


def test_handle_message_ignores_unknown_chat(monkeypatch, db):
    called = {}
    monkeypatch.setattr(
        "app.telegram.run_agent",
        lambda *a, **k: called.setdefault("hit", True) or "x",
    )
    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("TG_BOT_TOKEN", "x")
    monkeypatch.setenv("TG_CHAT_ID", "123")
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "s")
    handle_message(db, {"chat": {"id": 999}, "text": "x", "message_id": 1})
    assert "hit" not in called
