# Inline Keyboard Options Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the LLM agent's reply ends with a `[OPTIONS: a, b, c]` marker, render those options as Telegram inline-keyboard buttons; on tap, edit the original message to show the selection and route the choice back through `handle_message`.

**Architecture:** Pure additive changes to `app/telegram.py` (marker extraction in `send_reply`, new `handle_callback` for `callback_query` updates, two thin Bot API helper wrappers) and a 2-bullet append to `app/agent.py:SYSTEM_PROMPT`. No schema changes, no new modules.

**Tech Stack:** Python 3.12, FastAPI, httpx, Telegram Bot API (sendMessage with `reply_markup.inline_keyboard`, `answerCallbackQuery`, `editMessageText`).

**Spec:** `docs/superpowers/specs/2026-04-30-inline-keyboard-options-design.md`

---

## File map

**Modify:**
- `app/telegram.py` — add `_extract_options` parser, `answer_callback_query` + `edit_message_text` helpers, `handle_callback` function; update `send_reply` to honor the marker; extend `webhook` and `poll_updates_job` to route `callback_query` updates
- `app/agent.py` — append two bullets to `SYSTEM_PROMPT`
- `tests/test_telegram.py` — add ~10 tests

No new files. No schema changes.

---

## Task 1: `_extract_options` parser

Pure function, no I/O. TDD.

**Files:**
- Modify: `app/telegram.py`
- Modify: `tests/test_telegram.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_telegram.py`:

```python
from app.telegram import _extract_options


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
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_telegram.py::test_extract_options_with_simple_marker -v
```

Expected: ImportError (`_extract_options` does not exist).

- [ ] **Step 3: Implement `_extract_options`**

In `app/telegram.py`, add at the top (below imports, above `router = APIRouter()`):

```python
import re

_OPTIONS_RE = re.compile(r"^\[OPTIONS:\s*(.+?)\]\s*$")


def _extract_options(text: str) -> tuple[str, list[str] | None]:
    """If `text` ends with `[OPTIONS: a, b, c]` on its own line, return
    (text-without-marker, [opts]). Otherwise return (text, None).

    Empty option lists (e.g. `[OPTIONS:  ]`) are treated as no-options:
    the marker is stripped but no buttons are produced.
    """
    if not text:
        return text, None
    lines = text.rstrip().split("\n")
    if not lines:
        return text, None
    m = _OPTIONS_RE.match(lines[-1].strip())
    if not m:
        return text, None
    raw = m.group(1)
    options = [o.strip() for o in raw.split(",")]
    options = [o for o in options if o]
    cleaned = "\n".join(lines[:-1]).rstrip()
    return cleaned, (options or None)
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
.venv/bin/pytest tests/test_telegram.py -v -k "extract_options"
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add app/telegram.py tests/test_telegram.py
git commit -m "feat(telegram): add _extract_options marker parser"
```

---

## Task 2: `send_reply` honors the marker

Wire the parser into `send_reply` so a marker becomes an inline keyboard.

**Files:**
- Modify: `app/telegram.py`
- Modify: `tests/test_telegram.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_telegram.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_telegram.py -v -k "send_reply_attaches or send_reply_omits or send_reply_passes_reply_to_alongside"
```

Expected: 3 fail (current `send_reply` does not parse the marker; payload `text` still contains `[OPTIONS: ...]`).

- [ ] **Step 3: Update `send_reply`**

Replace the `send_reply` function in `app/telegram.py` with:

```python
def send_reply(chat_id: int, text: str, *, reply_to: int | None = None) -> None:
    settings = get_settings()
    visible_text, options = _extract_options(text)
    payload: dict = {"chat_id": chat_id, "text": visible_text}
    if reply_to is not None:
        payload["reply_to_message_id"] = reply_to
    if options:
        payload["reply_markup"] = {
            "inline_keyboard": [
                [{"text": o, "callback_data": o}] for o in options
            ]
        }
    url = f"https://api.telegram.org/bot{settings.tg_bot_token}/sendMessage"
    try:
        httpx.post(url, json=payload, timeout=10)
    except Exception:
        pass
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
.venv/bin/pytest tests/test_telegram.py -v
```

Expected: all telegram tests pass (existing 2 + 6 from Task 1 + 3 from this task = 11).

- [ ] **Step 5: Commit**

```bash
git add app/telegram.py tests/test_telegram.py
git commit -m "feat(telegram): render [OPTIONS:...] marker as inline keyboard"
```

---

## Task 3: Bot API helpers — `answer_callback_query` and `edit_message_text`

Two thin httpx wrappers. Tested for URL + payload shape.

**Files:**
- Modify: `app/telegram.py`
- Modify: `tests/test_telegram.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_telegram.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_telegram.py -v -k "answer_callback_query or edit_message_text"
```

Expected: 2 fail with ImportError.

- [ ] **Step 3: Add the helpers**

In `app/telegram.py`, add after `send_reply`:

```python
def answer_callback_query(callback_id: str) -> None:
    settings = get_settings()
    url = f"https://api.telegram.org/bot{settings.tg_bot_token}/answerCallbackQuery"
    try:
        httpx.post(url, json={"callback_query_id": callback_id}, timeout=10)
    except Exception:
        pass


def edit_message_text(chat_id: int, message_id: int, new_text: str) -> None:
    settings = get_settings()
    url = f"https://api.telegram.org/bot{settings.tg_bot_token}/editMessageText"
    try:
        httpx.post(
            url,
            json={"chat_id": chat_id, "message_id": message_id, "text": new_text},
            timeout=10,
        )
    except Exception:
        pass
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
.venv/bin/pytest tests/test_telegram.py -v -k "answer_callback_query or edit_message_text"
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add app/telegram.py tests/test_telegram.py
git commit -m "feat(telegram): add answerCallbackQuery and editMessageText helpers"
```

---

## Task 4: `handle_callback` function

Three-step click flow: ack → edit message → route choice through `handle_message`.

**Files:**
- Modify: `app/telegram.py`
- Modify: `tests/test_telegram.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_telegram.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_telegram.py -v -k "handle_callback"
```

Expected: 2 fail with ImportError.

- [ ] **Step 3: Implement `handle_callback`**

In `app/telegram.py`, add after `edit_message_text`:

```python
def handle_callback(db: Session, cb: dict) -> None:
    """Process a Telegram `callback_query` (inline keyboard tap)."""
    settings = get_settings()
    msg = cb.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id != settings.tg_chat_id:
        return
    selected = cb.get("data", "")
    original_text = msg.get("text", "")
    msg_id = msg.get("message_id")

    answer_callback_query(cb["id"])
    if msg_id is not None:
        edit_message_text(chat_id, msg_id, f"{original_text} → {selected} ✓")

    if not selected:
        return
    synth = {
        "chat": chat,
        "text": selected,
        "message_id": msg_id,
    }
    handle_message(db, synth)
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
.venv/bin/pytest tests/test_telegram.py -v
```

Expected: all telegram tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/telegram.py tests/test_telegram.py
git commit -m "feat(telegram): handle inline keyboard callback_query"
```

---

## Task 5: Wire `callback_query` into webhook + polling

Both update sources must dispatch callbacks alongside messages.

**Files:**
- Modify: `app/telegram.py`
- Modify: `tests/test_telegram.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_telegram.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
.venv/bin/pytest tests/test_telegram.py -v -k "callback_query"
```

Expected: 2 fail (current `webhook` and `poll_updates_job` ignore `callback_query`).

- [ ] **Step 3: Update `webhook`**

In `app/telegram.py`, replace the `webhook` function body:

```python
@router.post("/telegram/webhook")
async def webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    if x_telegram_bot_api_secret_token != settings.tg_webhook_secret:
        raise HTTPException(401, "bad secret")
    body = await request.json()
    msg = body.get("message") or body.get("edited_message")
    cb = body.get("callback_query")
    if msg:
        handle_message(db, msg)
    elif cb:
        handle_callback(db, cb)
    return {"ok": True}
```

- [ ] **Step 4: Update `poll_updates_job`**

In `app/telegram.py`, find the `for update in data.get("result", []):` loop in `poll_updates_job` and replace its body:

```python
        for update in data.get("result", []):
            last = update["update_id"]
            msg = update.get("message") or update.get("edited_message")
            cb = update.get("callback_query")
            if msg:
                handle_message(db, msg)
            elif cb:
                handle_callback(db, cb)
```

- [ ] **Step 5: Run tests to confirm pass**

```bash
.venv/bin/pytest tests/test_telegram.py -v
```

Expected: all telegram tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/telegram.py tests/test_telegram.py
git commit -m "feat(telegram): route callback_query in webhook and polling"
```

---

## Task 6: System prompt addition

Tell the LLM about the marker.

**Files:**
- Modify: `app/agent.py`
- Modify: `tests/test_agent.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent.py`:

```python
def test_system_prompt_documents_options_marker():
    from app.agent import SYSTEM_PROMPT
    assert "[OPTIONS:" in SYSTEM_PROMPT
    assert "마지막 줄" in SYSTEM_PROMPT
    assert "21자" in SYSTEM_PROMPT
```

- [ ] **Step 2: Run test to confirm failure**

```bash
.venv/bin/pytest tests/test_agent.py::test_system_prompt_documents_options_marker -v
```

Expected: AssertionError (`[OPTIONS:` not yet in prompt).

- [ ] **Step 3: Append the marker rule to `SYSTEM_PROMPT`**

In `app/agent.py`, find the `Style` section of `SYSTEM_PROMPT` (the block ending with the line about being concise) and append two bullets so it reads:

```
Style
- Reply in Korean.
- Use ✅ for success, ❓ for confirmations, ⚠️ for problems.
- Be concise. One short paragraph or 3-5 lines max.
- 사용자가 정해진 옵션 중에서 골라야 하는 상황이면, 답변 마지막 줄에
  단독으로 [OPTIONS: 옵션1, 옵션2, ...] 마커를 추가해라. 봇이 이걸
  인라인 버튼 카드로 변환한다.
- 옵션 라벨은 짧게 유지하라(한글 21자 이하). 마커는 반드시 마지막 줄에
  단독으로 두어라. 본문 중간에 두면 버튼이 만들어지지 않는다.
"""
```

(The closing `"""` is the end of the existing string literal; do not duplicate it.)

- [ ] **Step 4: Run test to confirm pass**

```bash
.venv/bin/pytest tests/test_agent.py -v
```

Expected: all agent tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/agent.py tests/test_agent.py
git commit -m "feat(agent): teach the LLM the [OPTIONS: ...] marker"
```

---

## Task 7: Final sweep + container deploy

- [ ] **Step 1: Run full suite**

```bash
.venv/bin/pytest -q
```

Expected: all green. Should be approximately 73-76 passed (was 64 + ~10 new).

- [ ] **Step 2: Lint files we touched**

```bash
.venv/bin/ruff check app/telegram.py app/agent.py tests/test_telegram.py tests/test_agent.py
```

Expected: `All checks passed!`. Fix any violations introduced by this work.

- [ ] **Step 3: Rebuild and restart container**

```bash
docker compose build && docker compose up -d
```

Expected: build success, container restart with no traceback in logs:

```bash
docker compose logs app | tail -20
```

- [ ] **Step 4: Manual e2e via Telegram**

Send these scenarios to the bot and confirm behavior:

| # | Send | Expect |
|---|---|---|
| 1 | `삼성전자 1주 80000에 매수` | Bot reply has 3 inline buttons (account choices); no `[OPTIONS:...]` text visible |
| 2 | Tap `삼성 ISA` button | Original prompt updates to "❓ … → 삼성 ISA ✓"; buttons gone; bot follows up with ✅ 매수 기록 |
| 3 | `오뚜기 1주 샀어` (or any new KR ticker → triggers account question) | Inline buttons again; tap one, confirm flow works |
| 4 | `방금 거 취소` then tap `예` (if confirm uses [OPTIONS: 예, 아니오]) | Cancel flow works through buttons |

If any scenario fails, capture container logs and fix in a follow-up commit before pushing.

- [ ] **Step 5: Commit any e2e fixes** (only if defects surfaced)

Each fix in its own commit, message starting with `fix(telegram):` or `fix(agent):`.

---

## Self-review summary

Spec sections vs. tasks:
- **Marker syntax** (spec §"Marker syntax") → Task 1
- **`send_reply` integration** (spec §"Components, app/telegram.py changes") → Task 2
- **`answer_callback_query`/`edit_message_text` helpers** → Task 3
- **`handle_callback` flow** (spec §"Click behavior") → Task 4
- **Webhook + polling routing** (spec §"Update routing") → Task 5
- **System prompt** (spec §"System prompt addition") → Task 6
- **Tests 1-8 from spec §"Tests"** are covered across Tasks 1-5 (count is similar though grouped differently — 6 parser tests + 3 send_reply + 2 helpers + 2 callback + 2 routing = 15, exceeding the spec's "8" floor with finer granularity).
- **Edge cases** (empty options, single option, mid-line marker, callback chat filter) are covered in Task 1 and Task 4 tests.
- **Manual e2e** → Task 7

Risks per spec mapped:
- Risk 1 (LLM ignores last-line rule): system prompt Task 6 + Task 1 mid-line test
- Risk 2 (callback_data overflow): system prompt Task 6 (label ≤ 21 chars). Failure mode logs only; not retried — acceptable per spec.
- Risk 3 (`editMessageText` race): not addressed in code per spec ("not worth fixing").

No placeholders. All steps include concrete code or commands with expected outputs.
