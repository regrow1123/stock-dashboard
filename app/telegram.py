import re
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.agent import get_window, run_agent
from app.api import get_db
from app.config import get_settings
from app.models import Meta

router = APIRouter()

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


def handle_message(db: Session, msg: dict) -> None:
    """Process a single Telegram 'message' dict via the agent."""
    settings = get_settings()
    chat_id = msg["chat"]["id"]
    if chat_id != settings.tg_chat_id:
        return
    text = msg.get("text", "")
    tg_message_id = msg["message_id"]
    if not text.strip():
        return

    window = get_window()
    now = datetime.now()
    window.append("user", text, at=now)
    reply = run_agent(text, window=window)
    window.append("assistant", reply, at=datetime.now())
    send_reply(chat_id, reply, reply_to=tg_message_id)


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
    if not msg:
        return {"ok": True}
    handle_message(db, msg)
    return {"ok": True}


def poll_updates_job(session_factory) -> None:
    """Long-poll getUpdates. Persist offset in the Meta table so we don't re-process."""
    db = session_factory()
    try:
        settings = get_settings()
        offset_row = db.get(Meta, "tg_offset")
        params = {"timeout": 25}
        if offset_row is not None:
            params["offset"] = int(offset_row.value) + 1
        url = f"https://api.telegram.org/bot{settings.tg_bot_token}/getUpdates"
        try:
            r = httpx.get(url, params=params, timeout=30)
            data = r.json()
        except Exception:
            return
        if not data.get("ok"):
            return
        last = None
        for update in data.get("result", []):
            last = update["update_id"]
            msg = update.get("message") or update.get("edited_message")
            if msg:
                handle_message(db, msg)
        if last is not None:
            if offset_row is None:
                db.add(Meta(key="tg_offset", value=str(last)))
            else:
                offset_row.value = str(last)
            db.commit()
    finally:
        if hasattr(db, "close"):
            db.close()
