"""Caps LLM calls per minute and per day, so public traffic stays inside Groq's limits.

Over the cap a call raises LLMError before reaching Groq, and the engine serves its
pre-ranked fallback instead of an error. Defaults fit gpt-oss-120b's 8K tokens/minute
(a search reserves about 2K) and 200K tokens/day (a search uses about 1.6K).
"""

import threading
import time
from collections import deque
from datetime import date, datetime, timezone

from recommender.llm.base import LLMClient, LLMError


class BudgetExceeded(LLMError):
    """The call would go over the per-minute or per-day cap."""


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


class BudgetedLLMClient:
    def __init__(self, inner: LLMClient, per_minute: int, per_day: int,
                 clock=time.monotonic, today=_utc_today):
        self.inner = inner
        self.per_minute = per_minute  # 0 = no cap
        self.per_day = per_day  # 0 = no cap; resets at midnight UTC
        self._clock, self._today = clock, today
        self._recent: deque[float] = deque()
        self._day, self._day_count = today(), 0
        self._lock = threading.Lock()

    def _take(self) -> None:
        with self._lock:
            now = self._clock()
            while self._recent and now - self._recent[0] >= 60:
                self._recent.popleft()
            if (day := self._today()) != self._day:
                self._day, self._day_count = day, 0
            if self.per_minute and len(self._recent) >= self.per_minute:
                raise BudgetExceeded(f"LLM budget reached: {self.per_minute} calls a minute")
            if self.per_day and self._day_count >= self.per_day:
                raise BudgetExceeded(f"LLM budget reached: {self.per_day} calls today")
            self._recent.append(now)
            self._day_count += 1

    def complete(self, system: str, user: str, response_schema: dict, max_tokens: int | None = None) -> str:
        self._take()
        return self.inner.complete(system, user, response_schema, max_tokens)

    def __getattr__(self, name):  # model, last_usage, ... of the wrapped client
        return getattr(self.inner, name)
