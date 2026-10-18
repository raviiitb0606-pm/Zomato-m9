from datetime import date

import pytest

from recommender.ratelimit import DAY_MESSAGE, MINUTE_MESSAGE, PRUNE_EVERY, Limited, RateLimiter


class Clock:
    def __init__(self):
        self.t, self.day = 1000.0, date(2026, 10, 18)

    def __call__(self):
        return self.t


def limiter(per_minute=2, per_day=5):
    clock = Clock()
    return RateLimiter(per_minute, per_day, clock=clock, today=lambda: clock.day), clock


def test_per_minute_limit_with_retry_after():
    rl, clock = limiter(per_minute=2, per_day=0)
    rl.hit("a")
    clock.t += 10
    rl.hit("a")
    with pytest.raises(Limited) as info:
        rl.hit("a")
    assert str(info.value) == MINUTE_MESSAGE and info.value.retry_after == 50
    clock.t += 50  # the first search has left the window
    rl.hit("a")


def test_per_day_limit_resets_at_midnight_utc():
    rl, clock = limiter(per_minute=0, per_day=2)
    rl.hit("a"), rl.hit("a")
    with pytest.raises(Limited, match=DAY_MESSAGE):
        rl.hit("a")
    clock.day = date(2026, 10, 19)
    rl.hit("a")


def test_visitors_are_counted_separately():
    rl, _ = limiter(per_minute=1)
    rl.hit("a"), rl.hit("b")
    with pytest.raises(Limited):
        rl.hit("a")


def test_refused_searches_do_not_count():
    rl, clock = limiter(per_minute=1, per_day=2)
    rl.hit("a")
    for _ in range(5):
        with pytest.raises(Limited):
            rl.hit("a")
    clock.t += 60
    rl.hit("a")  # still within the day: 2 counted, not 7


def test_idle_visitors_from_earlier_days_are_forgotten():
    rl, clock = limiter(per_minute=0, per_day=1000)
    rl.hit("old")
    clock.day = date(2026, 10, 19)
    for i in range(PRUNE_EVERY):
        rl.hit(f"v{i % 3}")
    assert "old" not in rl._visitors and len(rl) == 3
