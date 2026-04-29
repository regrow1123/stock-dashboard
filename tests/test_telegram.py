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


def test_send_reply_attaches_inline_keyboard_when_marker_present(monkeypatch):
    from app.telegram import send_reply
    from app.config import get_settings
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        class R: pass
        return R()
    monkeypatch.setattr("app.telegram.httpx.post", fake_post)
    monkeypatch.setenv("TG_BOT_TOKEN", "tok")
    monkeypatch.setenv("TG_CHAT_ID", "123")
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "s")
    get_settings.cache_clear()

    send_reply(123, "❓ 어느 계좌?\n[OPTIONS: A, B, C]")

    assert captured["url"].endswith("/sendMessage")
    payload = captured["json"]
    assert payload["chat_id"] == 123
    assert payload["text"] == "❓ 어느 계좌?"
    rm = payload["reply_markup"]
    assert rm == {
        "inline_keyboard": [
            [{"text": "A", "callback_data": "A"}],
            [{"text": "B", "callback_data": "B"}],
            [{"text": "C", "callback_data": "C"}],
        ]
    }


def test_send_reply_omits_reply_markup_when_no_marker(monkeypatch):
    from app.telegram import send_reply
    from app.config import get_settings
    captured = {}
    monkeypatch.setattr(
        "app.telegram.httpx.post",
        lambda url, json=None, timeout=None: captured.setdefault("json", json),
    )
    monkeypatch.setenv("TG_BOT_TOKEN", "tok")
    monkeypatch.setenv("TG_CHAT_ID", "123")
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "s")
    get_settings.cache_clear()

    send_reply(123, "✅ 매수 기록 완료")

    assert captured["json"]["text"] == "✅ 매수 기록 완료"
    assert "reply_markup" not in captured["json"]


def test_send_reply_passes_reply_to_alongside_keyboard(monkeypatch):
    from app.telegram import send_reply
    from app.config import get_settings
    captured = {}
    monkeypatch.setattr(
        "app.telegram.httpx.post",
        lambda url, json=None, timeout=None: captured.setdefault("json", json),
    )
    monkeypatch.setenv("TG_BOT_TOKEN", "tok")
    monkeypatch.setenv("TG_CHAT_ID", "123")
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "s")
    get_settings.cache_clear()

    send_reply(123, "Q?\n[OPTIONS: a, b]", reply_to=42)

    p = captured["json"]
    assert p["reply_to_message_id"] == 42
    assert "reply_markup" in p


def test_answer_callback_query_posts_to_correct_endpoint(monkeypatch):
    from app.telegram import answer_callback_query
    from app.config import get_settings
    captured = {}
    monkeypatch.setattr(
        "app.telegram.httpx.post",
        lambda url, json=None, timeout=None: captured.update(url=url, json=json),
    )
    monkeypatch.setenv("TG_BOT_TOKEN", "tok")
    monkeypatch.setenv("TG_CHAT_ID", "1")
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "s")
    get_settings.cache_clear()

    answer_callback_query("cbq_abc")

    assert captured["url"].endswith("/answerCallbackQuery")
    assert captured["json"] == {"callback_query_id": "cbq_abc"}


def test_edit_message_text_posts_chat_id_and_new_text(monkeypatch):
    from app.telegram import edit_message_text
    from app.config import get_settings
    captured = {}
    monkeypatch.setattr(
        "app.telegram.httpx.post",
        lambda url, json=None, timeout=None: captured.update(url=url, json=json),
    )
    monkeypatch.setenv("TG_BOT_TOKEN", "tok")
    monkeypatch.setenv("TG_CHAT_ID", "1")
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "s")
    get_settings.cache_clear()

    edit_message_text(123, 99, "❓ 어느 계좌? → 삼성 ISA ✓")

    assert captured["url"].endswith("/editMessageText")
    assert captured["json"] == {
        "chat_id": 123,
        "message_id": 99,
        "text": "❓ 어느 계좌? → 삼성 ISA ✓",
    }
