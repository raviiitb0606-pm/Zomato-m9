"""Per-visitor limits on /recommend, kept in memory (one server replica).

The visitor is identified by the `x-real-ip` header Vercel sets. That header is only
trustworthy because ORIGIN_SECRET makes sure requests came through Vercel; without a
proxy in front, the connection's address is used.
"""

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from fastapi import Request

MINUTE_MESSAGE = "Too many searches. Try again in a minute."
DAY_MESSAGE = "Daily search limit reached. Try again tomorrow."
PRUNE_EVERY = 500  # checks between sweeps of idle visitors


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _seconds_to_utc_midnight() -> int:
    now = datetime.now(timezone.utc)
    midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), timezone.utc)
    return max(1, math.ceil((midnight - now).total_seconds()))


def client_key(request: Request) -> str:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


@dataclass
class _Visitor:
    recent: deque = field(default_factory=deque)
    day: date | None = None
    day_count: int = 0


class Limited(Exception):
    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


class RateLimiter:
    def __init__(self, per_minute: int, per_day: int, clock=time.monotonic, today=_utc_today):
        self.per_minute = per_minute  # 0 = no limit
        self.per_day = per_day  # 0 = no limit; resets at midnight UTC
        self._clock, self._today = clock, today
        self._visitors: dict[str, _Visitor] = {}
        self._checks = 0
        self._lock = threading.Lock()

    def hit(self, key: str) -> None:
        """Count one search for `key`, or raise Limited if it is over a limit."""
        with self._lock:
            now, today = self._clock(), self._today()
            self._checks += 1
            if self._checks % PRUNE_EVERY == 0:
                self._prune(now, today)
            v = self._visitors.setdefault(key, _Visitor())
            while v.recent and now - v.recent[0] >= 60:
                v.recent.popleft()
            if v.day != today:
                v.day, v.day_count = today, 0
            if self.per_minute and len(v.recent) >= self.per_minute:
                raise Limited(MINUTE_MESSAGE, max(1, math.ceil(60 - (now - v.recent[0]))))
            if self.per_day and v.day_count >= self.per_day:
                raise Limited(DAY_MESSAGE, _seconds_to_utc_midnight())
            v.recent.append(now)
            v.day_count += 1

    def _prune(self, now: float, today: date) -> None:
        # Forgettable: a count from an earlier day, or (no daily limit) a minute without searches.
        idle = [k for k, v in self._visitors.items()
                if v.day != today or (not self.per_day and (not v.recent or now - v.recent[-1] >= 60))]
        for k in idle:
            del self._visitors[k]

    def __len__(self) -> int:
        return len(self._visitors)
