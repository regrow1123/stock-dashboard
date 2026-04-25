import json
import subprocess
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.config import get_settings


@dataclass
class ParseResult:
    type: str              # "trade" | "dividend" | "unknown"
    account: str | None
    ticker: str | None
    side: str | None
    quantity: float | None
    price: float | None
    amount: float | None   # dividends
    executed_at: date | None
    paid_at: date | None
    confidence: float
    note: str
    raw: dict[str, Any]


PROMPT = """You are a parser that converts a Korean user's stock trade/dividend report into JSON.

Allowed accounts:
{accounts}

Today is {today}. If the message uses relative dates like "오늘"/"어제", resolve to ISO date.

Return ONLY a compact JSON object (no prose, no markdown fences) matching:
{{
  "type": "trade" | "dividend" | "cancel" | "unknown",
  "account": "<one of allowed account id>" | null,
  "ticker": "<KR: 6-digit code with .KS or .KQ suffix; US: uppercase symbol>" | null,
  "side": "buy" | "sell" | null,
  "quantity": number | null,
  "price": number | null,
  "amount": number | null,
  "executed_at": "YYYY-MM-DD" | null,
  "paid_at": "YYYY-MM-DD" | null,
  "confidence": 0.0..1.0,
  "note": "<short reasoning>"
}}

Use type="cancel" when the user wants to undo or delete their most
recently submitted entry. Examples that map to cancel:
  - "방금 보낸 메시지 취소해줘"
  - "마지막 거래 취소"
  - "방금 거 잘못 입력했어 빼줘"
  - "직전 기록 삭제"
For cancel, set other fields to null and confidence to 0.95+ when the
intent is unambiguous.

Message:
{message}
"""


def parse_message(
    message: str, *, accounts: list[dict], today: date
) -> ParseResult:
    settings = get_settings()
    prompt = PROMPT.format(
        accounts="\n".join(f"- {a['id']}: {a['name']}" for a in accounts),
        today=today.isoformat(),
        message=message,
    )
    try:
        out = subprocess.run(
            [settings.claude_bin, "-p", prompt],
            capture_output=True, text=True, timeout=60, check=False,
        )
        data = json.loads(out.stdout.strip())
    except Exception:
        return ParseResult(
            type="unknown", account=None, ticker=None, side=None,
            quantity=None, price=None, amount=None,
            executed_at=None, paid_at=None,
            confidence=0.0, note="parse error", raw={},
        )

    def _d(key: str) -> date | None:
        v = data.get(key)
        return date.fromisoformat(v) if v else None

    return ParseResult(
        type=str(data.get("type", "unknown")),
        account=data.get("account"),
        ticker=data.get("ticker"),
        side=data.get("side"),
        quantity=data.get("quantity"),
        price=data.get("price"),
        amount=data.get("amount"),
        executed_at=_d("executed_at"),
        paid_at=_d("paid_at"),
        confidence=float(data.get("confidence", 0.0)),
        note=str(data.get("note", "")),
        raw=data,
    )
