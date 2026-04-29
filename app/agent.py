from __future__ import annotations

import subprocess
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

from app.config import get_settings


class SlidingWindow:
    def __init__(
        self,
        *,
        max_messages: int = 10,
        max_age: timedelta = timedelta(minutes=30),
    ) -> None:
        self._dq: deque[tuple[str, str, datetime]] = deque(maxlen=max_messages)
        self._max_age = max_age

    def append(self, role: str, text: str, *, at: datetime | None = None) -> None:
        self._dq.append((role, text, at or datetime.now()))

    def _alive(self, at: datetime) -> list[tuple[str, str, datetime]]:
        cutoff = at - self._max_age
        return [(r, t, ts) for r, t, ts in self._dq if ts >= cutoff]

    def render(self, *, at: datetime | None = None) -> str:
        now = at or datetime.now()
        rows = self._alive(now)
        if not rows:
            return "(empty — new session)"
        return "\n".join(f"{r}: {t}" for r, t, _ in rows)


SYSTEM_PROMPT = """You are a Telegram assistant for a single-user portfolio dashboard
holding Korean and US equities. Your job is to record trade/dividend
reports, answer holdings queries, and never lose or corrupt data.

Tools: t_list_accounts, t_list_holdings, t_recent_trades, t_recent_dividends,
t_search_ticker_kr, t_verify_ticker_us, t_lookup_ticker, t_record_trade,
t_record_dividend, t_cancel_trade, t_register_instrument.

Resolution rules
- KR stocks: the user reports by Korean name. First try t_lookup_ticker on
  any guess you have; on cache miss use t_search_ticker_kr. If 0 candidates,
  ASK the user. If 1, proceed but mention the ticker in your reply. If
  multiple, list them and ask.
- US stocks: the user reports by ticker. Verify with t_verify_ticker_us.
  If null (likely typo), ASK to confirm.
- Always pass `name` to t_record_trade / t_record_dividend when you've
  resolved a new ticker — this populates the cache.

Safety
- Before calling t_cancel_trade, send a summary and ask 예/아니오. Wait
  for user confirmation in the NEXT message before actually calling.
- If anything is ambiguous (which account, which trade, parse failure),
  ASK rather than guess.
- Currency rule: KRW accounts hold KR tickers (.KS/.KQ); USD accounts
  hold US tickers (no suffix). Never mix.

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


def build_prompt(*, window: SlidingWindow, message: str, at: datetime | None = None) -> str:
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Recent conversation (oldest → newest):\n{window.render(at=at)}\n\n"
        f"Latest message from user:\n{message}\n"
    )


_window_singleton = SlidingWindow()


def get_window() -> SlidingWindow:
    return _window_singleton


_ALLOWED_TOOLS = ",".join(f"mcp__dashboard__{n}" for n in (
    "t_list_accounts", "t_list_holdings", "t_recent_trades",
    "t_recent_dividends", "t_search_ticker_kr", "t_verify_ticker_us",
    "t_lookup_ticker", "t_record_trade", "t_record_dividend",
    "t_cancel_trade", "t_register_instrument",
))


def run_agent(message: str, *, window: SlidingWindow | None = None) -> str:
    settings = get_settings()
    win = window or get_window()
    prompt = build_prompt(window=win, message=message)
    cfg = str(Path("mcp.json").resolve())
    try:
        out = subprocess.run(
            [settings.claude_bin, "--mcp-config", cfg,
             "--allowedTools", _ALLOWED_TOOLS, "-p", prompt],
            capture_output=True, text=True, timeout=120, check=False,
        )
    except subprocess.TimeoutExpired:
        return "⚠️ 처리 시간이 초과되었습니다. 다시 시도해주세요."
    if out.returncode != 0:
        return f"⚠️ 오류: {out.stderr.strip()[:200] or 'agent failed'}"
    return out.stdout.strip()
