"""Scripted LLMClient for tests: no network, no key."""

import json


class FakeLLMClient:
    """Returns queued replies in order (or raises queued exceptions) and records every call."""

    def __init__(self, *replies: str | Exception):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def complete(self, system: str, user: str, response_schema: dict, max_tokens: int | None = None) -> str:
        self.calls.append({"system": system, "user": user, "response_schema": response_schema,
                           "max_tokens": max_tokens})
        if not self.replies:
            raise AssertionError("FakeLLMClient: no reply queued")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def reply_json(ids: list[str], summary: str = "Solid picks for this search.") -> str:
    """A well-formed reply ranking `ids` in order."""
    return json.dumps({
        "summary": summary,
        "ranking": [{"id": i, "explanation": f"Explanation for {i}."} for i in ids],
    })
