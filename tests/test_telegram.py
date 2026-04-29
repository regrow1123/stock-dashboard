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


def test_handle_callback_acks_edits_and_routes(monkeypatch, db):
    from app.telegram import handle_callback
    from app.config import get_settings
    monkeypatch.setenv("TG_BOT_TOKEN", "tok")
    monkeypatch.setenv("TG_CHAT_ID", "777")
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "s")
    get_settings.cache_clear()

    calls: list[tuple] = []
    monkeypatch.setattr(
        "app.telegram.answer_callback_query",
        lambda cid: calls.append(("ack", cid)),
    )
    monkeypatch.setattr(
        "app.telegram.edit_message_text",
        lambda chat, mid, txt: calls.append(("edit", chat, mid, txt)),
    )
    monkeypatch.setattr(
        "app.telegram.handle_message",
        lambda d, msg: calls.append(("msg", msg["text"], msg["chat"]["id"])),
    )

    cb = {
        "id": "cbq_xyz",
        "data": "삼성 ISA",
        "message": {
            "message_id": 55,
            "chat": {"id": 777, "type": "private"},
            "text": "❓ 어느 계좌인가요?",
        },
        "from": {"id": 777, "is_bot": False, "first_name": "u"},
    }

    handle_callback(db, cb)

    assert calls[0] == ("ack", "cbq_xyz")
    assert calls[1] == ("edit", 777, 55, "❓ 어느 계좌인가요? → 삼성 ISA ✓")
    assert calls[2] == ("msg", "삼성 ISA", 777)


def test_handle_callback_ignores_unknown_chat(monkeypatch, db):
    from app.telegram import handle_callback
    from app.config import get_settings
    monkeypatch.setenv("TG_BOT_TOKEN", "tok")
    monkeypatch.setenv("TG_CHAT_ID", "777")
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "s")
    get_settings.cache_clear()

    hits = {"acked": 0, "routed": 0}
    monkeypatch.setattr(
        "app.telegram.answer_callback_query",
        lambda cid: hits.__setitem__("acked", hits["acked"] + 1),
    )
    monkeypatch.setattr(
        "app.telegram.handle_message",
        lambda *a, **k: hits.__setitem__("routed", hits["routed"] + 1),
    )

    cb = {
        "id": "x",
        "data": "ignored",
        "message": {
            "message_id": 1,
            "chat": {"id": 999, "type": "private"},
            "text": "anything",
        },
    }
    handle_callback(db, cb)
    assert hits == {"acked": 0, "routed": 0}


def test_webhook_routes_callback_query(monkeypatch, engine):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.config import get_settings
    monkeypatch.setenv("TG_BOT_TOKEN", "tok")
    monkeypatch.setenv("TG_CHAT_ID", "42")
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "s")
    get_settings.cache_clear()

    routed = {"cb": 0, "msg": 0}
    monkeypatch.setattr(
        "app.telegram.handle_callback",
        lambda d, cb: routed.__setitem__("cb", routed["cb"] + 1),
    )
    monkeypatch.setattr(
        "app.telegram.handle_message",
        lambda d, m: routed.__setitem__("msg", routed["msg"] + 1),
    )

    app = create_app(engine=engine, start_scheduler=False)
    c = TestClient(app)
    body = {
        "update_id": 100,
        "callback_query": {
            "id": "cbq",
            "data": "X",
            "message": {
                "message_id": 1, "text": "?",
                "chat": {"id": 42, "type": "private"},
            },
        },
    }
    r = c.post(
        "/telegram/webhook", json=body,
        headers={"X-Telegram-Bot-Api-Secret-Token": "s"},
    )
    assert r.status_code == 200
    assert routed == {"cb": 1, "msg": 0}


def test_polling_processes_callback_query_update(monkeypatch, db):
    from app.telegram import poll_updates_job
    from app.config import get_settings
    monkeypatch.setenv("TG_BOT_TOKEN", "tok")
    monkeypatch.setenv("TG_CHAT_ID", "42")
    monkeypatch.setenv("TG_WEBHOOK_SECRET", "s")
    get_settings.cache_clear()

    routed = {"cb": 0, "msg": 0}
    monkeypatch.setattr(
        "app.telegram.handle_callback",
        lambda d, cb: routed.__setitem__("cb", routed["cb"] + 1),
    )
    monkeypatch.setattr(
        "app.telegram.handle_message",
        lambda d, m: routed.__setitem__("msg", routed["msg"] + 1),
    )

    def fake_get(url, params=None, timeout=None):
        class R:
            def json(self):
                return {
                    "ok": True,
                    "result": [
                        {"update_id": 11, "callback_query": {
                            "id": "x", "data": "X",
                            "message": {
                                "message_id": 1, "text": "?",
                                "chat": {"id": 42, "type": "private"},
                            },
                        }},
                    ],
                }
        return R()
    monkeypatch.setattr("app.telegram.httpx.get", fake_get)

    poll_updates_job(session_factory=lambda: db)
    assert routed == {"cb": 1, "msg": 0}
