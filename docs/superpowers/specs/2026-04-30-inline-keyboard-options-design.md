# Inline Keyboard Options — Design Spec

**Date:** 2026-04-30
**Status:** Design approved, pending implementation plan

## Background

After the agent redesign (`docs/superpowers/specs/2026-04-29-telegram-agent-redesign-design.md`), the Telegram bot frequently asks the user to choose between specific options — most commonly the account when a trade message is account-ambiguous, or which of N candidate tickers a Korean stock name resolves to. Today these prompts arrive as plain text:

> ❓ 뉴로핏(380550.KQ) 5주 @22,000원 매수 — 어느 KRW 계좌인가요?
> - 삼성 ISA / 삼성 IRP / 삼성 연금저축

The user must type the answer back. On mobile this is friction; on a phone keyboard a misspelled answer ("삼성ISA" vs "삼성 ISA") forces another round-trip. Telegram's inline keyboard ("card-style buttons") solves this — the agent can offer one-tap selection.

## Goal

Let the LLM agent attach Telegram inline-keyboard buttons to its replies when the user must choose among a small finite set of options. Selecting a button feeds the chosen text back through the same `handle_message → run_agent` flow, so no agent-side logic changes beyond a system-prompt addition.

In-scope:
- Account disambiguation ("어느 계좌?")
- Yes/no confirmations ("매수 취소할까요?")
- Ticker disambiguation when search returns multiple candidates

Out-of-scope (deferred):
- Multi-select (today: single-select only)
- Persistent UI state across multiple turns (today: each prompt is a single Q&A round)
- Inline mode / `@bot ...` queries

## Architecture

### Data flow

```
User: "뉴로핏 5주 22000에 매수"
    ↓ handle_message → run_agent → claude -p subprocess
LLM reply text (raw):
    "❓ 어느 계좌인가요?\n[OPTIONS: 삼성 ISA, 삼성 IRP, 삼성 연금저축]"
    ↓ send_reply
Bot detects [OPTIONS:...] on the last line, splits into:
    - visible_text:  "❓ 어느 계좌인가요?"
    - options:       ["삼성 ISA", "삼성 IRP", "삼성 연금저축"]
    ↓
Telegram sendMessage with reply_markup.inline_keyboard:
    [[{"text": "삼성 ISA", "callback_data": "삼성 ISA"}],
     [{"text": "삼성 IRP", "callback_data": "삼성 IRP"}],
     [{"text": "삼성 연금저축", "callback_data": "삼성 연금저축"}]]
    ↓
User taps "삼성 ISA"
    ↓ Telegram delivers a callback_query update (NOT a message update)
Bot's handle_callback (new):
    1. answerCallbackQuery(callback_id)        # Telegram requires ack ≤30s
    2. editMessageText(chat, msg_id,
           text="❓ 어느 계좌인가요? → 삼성 ISA ✓")  # transcript update
    3. Synthesize a user message {chat, text="삼성 ISA", message_id=...}
       and call handle_message(db, fake_msg)
    ↓
handle_message → run_agent → ✅ 매수 기록...
```

### Marker syntax

`[OPTIONS: opt1, opt2, opt3]`

- Must be the **last non-empty line** of the LLM's reply
- Comma-separated; each option's leading/trailing whitespace is stripped
- Each option ≤ 21 Korean chars (Telegram callback_data 64-byte limit, 3 bytes/Korean char). Soft-enforced via system prompt; if exceeded, sendMessage will fail and the bot falls back to plain text (option preview in error log).
- Detection regex: `^\[OPTIONS:\s*(.+?)\]\s*$` against the trimmed last line. Match → strip from text + extract options.
- If the LLM puts the marker mid-message, it is treated as ordinary text (no buttons created). System prompt explicitly warns against this.

### Click behavior

After the user taps a button, the bot performs three actions in order:

1. **`answerCallbackQuery(callback_id)`** — required by Telegram, must complete within 30 s. If we skip it, Telegram retries the callback and the user sees a permanent loading spinner on the button.
2. **`editMessageText(chat_id, message_id, text=<new>)`** — rewrites the original prompt to show the choice as a transcript entry. Format: `<original visible text> → <selected option> ✓`. Uses `parse_mode="HTML"` not at all (plain text only) to avoid escaping concerns.
3. **Synthesize a `message` dict and call `handle_message(db, msg)`** — feeds the selection through the existing agent path. The synthesized message has:
   - `chat`: copied from the callback's `message.chat`
   - `text`: `callback_query.data` (the selected option)
   - `message_id`: a synthetic value (we use `callback_query.message.message_id` — the bot's own message id — purely so `reply_to` in the next bot reply has *some* anchor; semantically it's the user's "selection" event)

The agent's reply then proceeds normally; if it itself contains an `[OPTIONS: ...]` marker, the loop continues.

### Update routing

The webhook and polling paths currently look only for `message`/`edited_message` keys. They are extended with one branch:

```python
msg = update.get("message") or update.get("edited_message")
cb  = update.get("callback_query")
if msg:
    handle_message(db, msg)
elif cb:
    handle_callback(db, cb)
```

`handle_callback` filters by `chat_id` exactly the same way `handle_message` does (drop messages from chats other than the configured `tg_chat_id`).

### System prompt addition

Append to `app/agent.py:SYSTEM_PROMPT` (Style section):

```
- 사용자가 정해진 옵션 중에서 골라야 하는 상황이면, 답변 마지막 줄에
  단독으로 [OPTIONS: 옵션1, 옵션2, ...] 마커를 추가해라. 봇이 이걸
  인라인 버튼 카드로 변환한다.
- 옵션 라벨은 짧게 유지하고(한글 21자 이하), 마커는 반드시 마지막 줄에
  단독으로 두어라. 본문 중간에 두면 버튼이 만들어지지 않는다.
```

## Components

### `app/telegram.py` changes

New helpers (private to module unless reused):

- `_OPTIONS_RE = re.compile(r"^\[OPTIONS:\s*(.+?)\]\s*$")` — last-line matcher
- `_extract_options(text) -> tuple[str, list[str] | None]` — returns (cleaned_text, options) where options is `None` if no marker
- `answer_callback_query(callback_id: str) -> None` — POSTs `answerCallbackQuery`
- `edit_message_text(chat_id, message_id, new_text) -> None` — POSTs `editMessageText`
- `handle_callback(db, cb: dict) -> None` — three-step click handling above

`send_reply(chat_id, text, *, reply_to=None)` is updated:
- Calls `_extract_options(text)` first
- If options present, attaches `reply_markup={"inline_keyboard": [[{"text": o, "callback_data": o}] for o in options]}` and uses cleaned_text
- If no options, behavior unchanged from current

`webhook` and `poll_updates_job` add the `callback_query` branch shown above.

### `app/agent.py` changes

Single `SYSTEM_PROMPT` text edit (the new bullet at the end of the Style section). No structural changes.

### Tests

`tests/test_telegram.py` adds the following tests, all using `monkeypatch` against `app.telegram.httpx.post` (no real network):

1. `test_send_reply_with_options_marker_attaches_inline_keyboard` — verifies POSTed payload has `reply_markup.inline_keyboard` with one row per option
2. `test_send_reply_strips_marker_from_visible_text` — `text` field in payload does not contain `[OPTIONS:...]`
3. `test_send_reply_without_marker_omits_reply_markup` — backward compatibility
4. `test_send_reply_handles_marker_with_extra_whitespace` — `[OPTIONS:  a ,  b  ]` parses to `["a", "b"]`
5. `test_send_reply_ignores_marker_not_on_last_line` — mid-message marker is left in text, no keyboard
6. `test_handle_callback_acks_edits_and_routes` — verifies in order: `answerCallbackQuery` → `editMessageText` (with `→ <choice> ✓` suffix) → `handle_message` synth dispatched. Mocks `run_agent` to return a fixed string.
7. `test_handle_callback_ignores_unknown_chat` — chat_id filter symmetry with `handle_message`
8. `test_webhook_routes_callback_query` — POST a body containing only `callback_query` → `handle_callback` invoked, `handle_message` NOT invoked

### Edge cases

- **Empty options after parse** (`[OPTIONS: ]`): treat as no-marker, send as plain text. The marker line is stripped though, so the user sees a clean message; alternatively we leave it in. Decision: strip + no keyboard (the trailing `[OPTIONS: ]` would be confusing if shown).
- **Single option** (`[OPTIONS: 예]`): rendered as a single button. Allowed — useful for "tap to confirm" UX.
- **callback_data > 64 bytes**: Telegram's `sendMessage` returns an error; bot logs and falls back to plain text (no keyboard). The user sees the question without buttons but can still type. Not retried.
- **User taps button after the bot is restarted**: the in-memory sliding window for that chat is empty, so the agent loses context. The selection text alone is usually meaningful enough ("삼성 ISA") that the agent can ask again with full context. Acceptable trade-off vs. persisting window state.
- **Repeated callback** from the same user (double-tap): Telegram delivers two callback_query updates. The first edits the message; the second's `editMessageText` will succeed (idempotent) and trigger a second `handle_message` round, posting two `✅ 매수 기록` replies. Acceptable for a single-user bot.

## Migration

Single PR; no schema changes; no data migration. Prior text-only prompts continue to work because the marker is opt-in. Backward compatible.

## Risks

1. **LLM doesn't respect "last line" rule.** Mitigation: regex strictly checks the last line; mid-message markers are preserved as text. The user sees the unparsed marker but the flow doesn't break. We can iterate on the prompt phrasing if this happens often.
2. **callback_data length overflow.** Mitigation: system prompt asks for short labels. Failure mode is graceful (no keyboard, plain text).
3. **`editMessageText` race vs. `handle_message`.** If `editMessageText` is slow, the agent reply may arrive before the prompt's transcript update is committed in the chat. Visually, this means the user briefly sees:
   - prompt with buttons
   - agent's ✅ reply
   - prompt updates to "→ 선택 ✓"
   The mis-order is brief and self-correcting; not worth fixing.
