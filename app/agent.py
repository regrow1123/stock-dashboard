from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta


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
