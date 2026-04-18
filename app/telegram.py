import json
from dataclasses import asdict
from datetime import date

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.api import get_db
from app.config import get_settings
from app.models import Account, Dividend, Meta, PendingConfirm, Trade
from app.parser import parse_message
from app.snapshots import recompute_snapshots

router = APIRouter()

CONFIDENCE_THRESHOLD = 0.8


def send_reply(chat_id: int, text: str, *, reply_to: int | None = None) -> None:
    settings = get_settings()
    payload = {"chat_id": chat_id, "text": text}
    if reply_to is not None:
        payload["reply_to_message_id"] = reply_to
    url = f"https://api.telegram.org/bot{settings.tg_bot_token}/sendMessage"
    try:
        httpx.post(url, json=payload, timeout=10)
    except Exception:
        pass


def _confirm_text(p) -> str:
    if p.type == "trade":
        return (
            f"❓ 이렇게 기록할까요?\n"
            f"- 계좌: {p.account}\n- 종목: {p.ticker}\n- {p.side} {p.quantity}@{p.price}\n"
            f"- 날짜: {p.executed_at}\n(예/아니오)"
        )
    if p.type == "dividend":
        return (
            f"❓ 배당으로 기록할까요?\n"
            f"- 계좌: {p.account}\n- 종목: {p.ticker}\n"
            f"- 금액: {p.amount}\n- 지급일: {p.paid_at}\n(예/아니오)"
        )
    return "❓ 해석하지 못했습니다. 계좌/종목/수량/가격/날짜를 다시 알려주세요."


_SIDE_KO = {"buy": "매수", "sell": "매도"}


def _success_text(p) -> str:
    if p.type == "trade":
        side_ko = _SIDE_KO.get(p.side, p.side)
        return f"✅ {side_ko} {p.ticker} {p.quantity}@{p.price} ({p.account}) 기록"
    if p.type == "dividend":
        return f"✅ 배당 {p.ticker} {p.amount} ({p.account}) 기록"
    return "✅ 기록"


def _save_and_recompute(db: Session, p, tg_message_id: int, raw_text: str) -> None:
    if p.type == "trade":
        db.add(
            Trade(
                account_id=p.account, ticker=p.ticker, side=p.side,
                quantity=float(p.quantity), price=float(p.price),
                executed_at=p.executed_at, raw_text=raw_text,
                tg_message_id=tg_message_id,
            )
        )
        db.commit()
        from datetime import date as _date
        recompute_snapshots(
            db, from_date=p.executed_at, to_date=_date.today(),
            account_id=p.account,
        )
    elif p.type == "dividend":
        db.add(
            Dividend(
                account_id=p.account, ticker=p.ticker, amount=float(p.amount),
                paid_at=p.paid_at, raw_text=raw_text, tg_message_id=tg_message_id,
            )
        )
        db.commit()


def handle_message(db: Session, msg: dict) -> None:
    """Process a single Telegram 'message' dict. Used by webhook + polling."""
    settings = get_settings()
    chat_id = msg["chat"]["id"]
    if chat_id != settings.tg_chat_id:
        return
    text = msg.get("text", "")
    tg_message_id = msg["message_id"]

    # yes/no follow-up for pending confirms
    if text.strip().lower() in {"예", "네", "yes", "y", "아니오", "아니요", "no", "n"}:
        pending = (
            db.query(PendingConfirm)
            .order_by(PendingConfirm.created_at.desc())
            .first()
        )
        if pending is not None:
            if text.strip().lower() in {"예", "네", "yes", "y"}:
                from app.parser import ParseResult
                d = json.loads(pending.payload_json)
                p = ParseResult(
                    **{**d,
                       "executed_at": date.fromisoformat(d["executed_at"]) if d.get("executed_at") else None,
                       "paid_at": date.fromisoformat(d["paid_at"]) if d.get("paid_at") else None}
                )
                _save_and_recompute(db, p, tg_message_id, "(confirmed)")
                send_reply(chat_id, _success_text(p), reply_to=tg_message_id)
            else:
                send_reply(chat_id, "👍 취소했습니다.", reply_to=tg_message_id)
            db.delete(pending)
            db.commit()
        return

    accounts = [
        {"id": a.id, "name": a.name}
        for a in db.query(Account).order_by(Account.display_order).all()
    ]
    parsed = parse_message(text, accounts=accounts, today=date.today())

    # Route to pending if confidence is low, type is unknown, or required fields are missing
    def _needs_confirm(p) -> bool:
        if p.type == "unknown" or p.confidence < CONFIDENCE_THRESHOLD:
            return True
        if p.type == "trade":
            return not all([p.account, p.ticker, p.side, p.quantity, p.price, p.executed_at])
        if p.type == "dividend":
            return not all([p.account, p.ticker, p.amount, p.paid_at])
        return True

    if _needs_confirm(parsed):
        payload = asdict(parsed)
        payload["executed_at"] = parsed.executed_at.isoformat() if parsed.executed_at else None
        payload["paid_at"] = parsed.paid_at.isoformat() if parsed.paid_at else None
        payload.pop("raw", None)
        db.add(PendingConfirm(tg_message_id=tg_message_id, payload_json=json.dumps(payload)))
        db.commit()
        send_reply(chat_id, _confirm_text(parsed), reply_to=tg_message_id)
        return

    _save_and_recompute(db, parsed, tg_message_id, text)
    send_reply(chat_id, _success_text(parsed), reply_to=tg_message_id)


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
