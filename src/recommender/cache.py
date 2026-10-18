"""In-memory LRU of finished responses, so a repeated search costs no LLM tokens (edge cases CAC-01 to CAC-07)."""

import threading
from collections import OrderedDict

from recommender.prompt import PROMPT_VERSION
from recommender.schemas import Preferences, RecommendationResponse


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def cache_key(prefs: Preferences, model: str) -> tuple:
    """The same search typed differently gives one key (CAC-01); different extras don't
    (CAC-02); a new prompt or model starts fresh (CAC-06)."""
    return (
        PROMPT_VERSION, model, _norm(prefs.location), prefs.budget,
        tuple(sorted({_norm(c) for c in prefs.cuisine})), round(prefs.min_rating, 2),
        _norm(prefs.extras), prefs.top_k,
    )


class ResponseCache:
    """Least-recently-used, capped at `max_size` (CAC-07). Safe across the API's worker threads."""

    def __init__(self, max_size: int):
        self.max_size = max_size
        self._items: OrderedDict[tuple, RecommendationResponse] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple) -> RecommendationResponse | None:
        with self._lock:
            resp = self._items.get(key)
            if resp is None:
                return None
            self._items.move_to_end(key)
        return resp.model_copy(deep=True)  # callers can't change what's stored

    def put(self, key: tuple, resp: RecommendationResponse) -> None:
        stored = resp.model_copy(deep=True)
        with self._lock:
            self._items[key] = stored
            self._items.move_to_end(key)
            while len(self._items) > self.max_size:
                self._items.popitem(last=False)

    def __len__(self) -> int:
        return len(self._items)
