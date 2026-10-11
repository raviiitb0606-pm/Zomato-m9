"""Recommendation engine: shortlist -> LLM -> validate -> response (architecture.md §5.5).

CLI: python -m recommender.engine --location Indiranagar --budget medium --cuisine Chinese
"""

import argparse
import logging
import sys
import time

from recommender.llm.base import LLMClient, LLMError
from recommender.prompt import (
    RESPONSE_SCHEMA, SYSTEM_PROMPT, LLMReply, ReplyError, build_user_prompt, parse_reply, pick_count,
)
from recommender.schemas import Preferences, Recommendation, RecommendationResponse, Restaurant
from recommender.store import RestaurantStore

log = logging.getLogger(__name__)

MAX_EXPLANATION_CHARS = 500
FALLBACK_SUMMARY = "Top matches ranked by rating and number of reviews."


def template_explanation(r: Restaurant) -> str:
    """Plain facts from the data; missing values are left out, never printed as None."""
    parts = []
    if r.rating is not None:
        parts.append(f"Rated {r.rating:g} from {r.votes:,} votes")
    else:
        parts.append("Not yet rated")
    if r.cuisines:
        parts.append(f"serves {', '.join(r.cuisines[:3])}")
    if r.cost_for_two is not None:
        parts.append(f"about ₹{r.cost_for_two:,} for two")
    if r.locality:
        parts.append(f"in {r.locality}")
    return "; ".join(parts) + "."


def _trim(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= MAX_EXPLANATION_CHARS:
        return text
    cut = text[:MAX_EXPLANATION_CHARS]
    end = cut.rfind(". ")
    return cut[:end + 1] if end > 0 else cut.rstrip() + "…"


def _retry_prompt(user: str, error: ReplyError) -> str:
    reason = str(error)[:200]
    return (f"{user}\n\nYour previous reply could not be used ({reason}). "
            "Reply again with JSON only, in the required shape.")


class Engine:
    def __init__(self, store: RestaurantStore, llm: LLMClient, shortlist_size: int | None = None):
        self.store = store
        self.llm = llm
        self.shortlist_size = shortlist_size

    @classmethod
    def from_settings(cls) -> "Engine":
        from recommender.llm.groq_client import GroqClient

        return cls(RestaurantStore.load(), GroqClient.from_settings())

    def _ask_llm(self, prefs: Preferences, candidates: list[Restaurant]) -> LLMReply | None:
        """The model's reply, or None if it failed. Malformed replies get one retry."""
        user = build_user_prompt(prefs, candidates)
        try:
            return parse_reply(self.llm.complete(SYSTEM_PROMPT, user, RESPONSE_SCHEMA))
        except LLMError as exc:
            log.warning("llm failed, using fallback: %s", exc)
            return None
        except ReplyError as exc:
            log.warning("llm reply malformed, retrying once: %s", exc)
            retry_user = _retry_prompt(user, exc)
        try:
            return parse_reply(self.llm.complete(SYSTEM_PROMPT, retry_user, RESPONSE_SCHEMA))
        except (LLMError, ReplyError) as exc:
            log.warning("llm retry failed, using fallback: %s", exc)
            return None

    def recommend(self, prefs: Preferences) -> RecommendationResponse:
        shortlist = self.store.query(prefs, size=self.shortlist_size)
        candidates = shortlist.restaurants
        if not candidates:
            return RecommendationResponse(message=shortlist.message)

        want = pick_count(prefs.top_k, candidates)
        reply = self._ask_llm(prefs, candidates)

        # Keep the model's picks that are real, unique shortlist ids, in its order.
        by_key = {r.id.lower(): r for r in candidates}
        picked: list[tuple[Restaurant, str, str]] = []
        seen: set[str] = set()
        dropped = 0
        for item in (reply.ranking if reply else []):
            r = by_key.get(item.id.strip().lower())
            if r is None or r.id in seen:
                dropped += 1
                continue
            seen.add(r.id)
            explanation = _trim(item.explanation)
            if explanation:
                picked.append((r, explanation, "llm"))
            else:
                picked.append((r, template_explanation(r), "template"))
            if len(picked) == want:
                break
        if dropped:
            log.info("dropped %d unknown or duplicate ids from the llm reply", dropped)

        # Top up from the pre-ranked shortlist (all of it, on fallback).
        for r in candidates:
            if len(picked) == want:
                break
            if r.id not in seen:
                seen.add(r.id)
                picked.append((r, template_explanation(r), "template"))

        llm_fallback = not any(source == "llm" for _, _, source in picked)
        summary = FALLBACK_SUMMARY if llm_fallback else (reply.summary.strip() or "")
        return RecommendationResponse(
            summary=summary,
            recommendations=[
                Recommendation(
                    rank=rank, id=r.id, name=r.name, cuisine=r.cuisines, rating=r.rating,
                    estimated_cost=r.cost_for_two, explanation=explanation, explanation_source=source,
                )
                for rank, (r, explanation, source) in enumerate(picked, 1)
            ],
            relaxed_constraints=shortlist.relaxed_constraints,
            llm_fallback=llm_fallback,
            message=shortlist.message,
        )


def main(argv: list[str] | None = None, engine: Engine | None = None) -> int:
    p = argparse.ArgumentParser(description="Run one recommendation end to end.")
    p.add_argument("--location", required=True, help="Bangalore or a neighbourhood")
    p.add_argument("--budget", choices=("low", "medium", "high"))
    p.add_argument("--cuisine", action="append", default=[], help="repeatable, or comma-separated")
    p.add_argument("--min-rating", type=float, default=0.0)
    p.add_argument("--extras", default="")
    p.add_argument("--top-k", type=int, default=5)
    args = p.parse_args(argv)

    from pydantic import ValidationError

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        prefs = Preferences(location=args.location, budget=args.budget,
                            cuisine=[c for arg in args.cuisine for c in arg.split(",")],
                            min_rating=args.min_rating, extras=args.extras, top_k=args.top_k)
    except ValidationError as exc:
        print(exc, file=sys.stderr)
        return 2
    engine = engine or Engine.from_settings()

    start = time.perf_counter()
    resp = engine.recommend(prefs)
    elapsed = time.perf_counter() - start

    for r in resp.relaxed_constraints:
        print(f"Relaxed: {r}")
    if resp.message:
        print(f"Note: {resp.message}")
    if resp.summary:
        print(f"Summary: {resp.summary}\n")
    for rec in resp.recommendations:
        cost = f"₹{rec.estimated_cost}" if rec.estimated_cost is not None else "cost n/a"
        print(f"{rec.rank}. {rec.name} | {', '.join(rec.cuisine)} | rating {rec.rating} | {cost}")
        print(f"   [{rec.explanation_source}] {rec.explanation}")

    # Exit check: every fact shown must equal the dataset row.
    rows = {r.id: r for r in engine.store.get([rec.id for rec in resp.recommendations])}
    mismatches = [
        rec.id for rec in resp.recommendations
        if (rec.id not in rows
            or (rec.name, rec.cuisine, rec.rating, rec.estimated_cost)
            != (rows[rec.id].name, rows[rec.id].cuisines, rows[rec.id].rating, rows[rec.id].cost_for_two))
    ]
    print(f"\n{len(resp.recommendations)} of top_k={prefs.top_k} returned | llm_fallback={resp.llm_fallback} "
          f"| facts match dataset: {'yes' if not mismatches else f'NO {mismatches}'} | {elapsed:.2f}s")
    return 0 if not mismatches else 1


if __name__ == "__main__":
    sys.exit(main())
