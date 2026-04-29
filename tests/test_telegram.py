from app.telegram import handle_message, _extract_options


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


def test_extract_options_with_simple_marker():
    text = "❓ 어느 계좌인가요?\n[OPTIONS: 삼성 ISA, 삼성 IRP, 삼성 연금저축]"
    cleaned, options = _extract_options(text)
    assert cleaned == "❓ 어느 계좌인가요?"
    assert options == ["삼성 ISA", "삼성 IRP", "삼성 연금저축"]


def test_extract_options_handles_extra_whitespace():
    text = "Pick one\n[OPTIONS:  a ,  b  ,c ]"
    cleaned, options = _extract_options(text)
    assert cleaned == "Pick one"
    assert options == ["a", "b", "c"]


def test_extract_options_returns_none_when_no_marker():
    text = "Just a regular reply."
    cleaned, options = _extract_options(text)
    assert cleaned == text
    assert options is None


def test_extract_options_ignores_marker_not_on_last_line():
    text = "[OPTIONS: a, b]\nactual content here"
    cleaned, options = _extract_options(text)
    assert cleaned == text
    assert options is None


def test_extract_options_handles_empty_options_as_no_marker():
    text = "Question?\n[OPTIONS:  ]"
    cleaned, options = _extract_options(text)
    # Marker is stripped (no point showing it) but no buttons created.
    assert cleaned == "Question?"
    assert options is None


def test_extract_options_allows_single_option():
    text = "Confirm?\n[OPTIONS: 예]"
    cleaned, options = _extract_options(text)
    assert cleaned == "Confirm?"
    assert options == ["예"]
