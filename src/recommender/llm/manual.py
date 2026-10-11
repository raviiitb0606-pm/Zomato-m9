"""One real Groq call on a fixed 10-restaurant shortlist: python -m recommender.llm.manual

Phase 3 exit check. Costs one request (two if the SDK retries a transient error).
"""

import logging
import sys

from recommender.config import get_settings
from recommender.llm.base import LLMError
from recommender.llm.groq_client import GroqClient
from recommender.prompt import (
    PROMPT_VERSION, RESPONSE_SCHEMA, SYSTEM_PROMPT, ReplyError, build_user_prompt, parse_reply, pick_count,
)
from recommender.schemas import Preferences
from recommender.store import RestaurantStore

# "family-friendly" can't be judged from the data: the explanations should say so.
PREFS = Preferences(location="Koramangala", budget="high", cuisine=["Italian", "Continental"],
                    min_rating=4.0, extras="family-friendly, good for a relaxed dinner", top_k=5)
SHORTLIST_SIZE = 10
TPM_LIMIT = 8000  # Groq tokens/minute seen on this account (x-ratelimit-limit-tokens)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    candidates = RestaurantStore.load().query(PREFS, size=SHORTLIST_SIZE).restaurants
    user = build_user_prompt(PREFS, candidates)
    print(f"Model {settings.llm_model}, prompt v{PROMPT_VERSION}, {len(candidates)} candidates\n")

    client = GroqClient.from_settings(settings)
    try:
        text = client.complete(SYSTEM_PROMPT, user, RESPONSE_SCHEMA)
    except LLMError as exc:
        print(f"FAILED: {exc}")
        return 1

    by_id = {r.id: r for r in candidates}
    try:
        reply = parse_reply(text)
    except ReplyError as exc:
        print(f"FAILED to parse: {exc}\nRaw reply:\n{text}")
        return 1

    for rank, item in enumerate(reply.ranking, 1):
        r = by_id.get(item.id)
        facts = (f"{r.name} | {', '.join(r.cuisines)} | rating {r.rating} ({r.votes} votes) | "
                 f"₹{r.cost_for_two} for two | {r.locality} | tags: {', '.join(r.tags)}") if r else "NOT IN SHORTLIST"
        print(f"{rank}. [{item.id}] {facts}\n   -> {item.explanation}\n")
    print(f"Summary: {reply.summary}\n")

    ids = [item.id for item in reply.ranking]
    want = pick_count(PREFS.top_k, candidates)
    checks = {
        "valid JSON in the expected shape": True,
        "only shortlist ids": all(i in by_id for i in ids),
        "no duplicate ids": len(ids) == len(set(ids)),
        f"exactly {want} picks": len(ids) == want,
    }
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")

    u = client.last_usage
    reserved = u.prompt_tokens + settings.llm_max_completion_tokens
    print(f"\nLatency {client.last_latency_s:.2f}s | tokens: prompt {u.prompt_tokens}, "
          f"completion {u.completion_tokens}")
    print(f"Counted against the {TPM_LIMIT} tokens/min limit: about {reserved} per request "
          f"(prompt + max_completion_tokens {settings.llm_max_completion_tokens}) "
          f"-> roughly {TPM_LIMIT // reserved} requests/min at this shortlist size")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
