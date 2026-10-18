"""Groq implementation of LLMClient (implementation-plan.md, Phase 3)."""

import logging
import time

import groq
from groq import Groq

from recommender.config import Settings, get_settings
from recommender.llm.base import LLMError, MalformedReplyError

log = logging.getLogger(__name__)

# On Groq these support strict structured outputs and reasoning controls.
STRICT_JSON_PREFIX = "openai/gpt-oss-"
# 400 codes Groq returns instead of a reply that isn't valid JSON or doesn't match the schema.
UNUSABLE_REPLY_CODES = {"json_validate_failed", "output_parse_failed"}


def _is_unusable_reply(exc: groq.APIError) -> bool:
    body = exc.body if isinstance(exc, groq.BadRequestError) else None
    error = body.get("error") if isinstance(body, dict) else None
    return isinstance(error, dict) and error.get("code") in UNUSABLE_REPLY_CODES


class GroqClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout_s: float = 30.0,
        reasoning_effort: str = "low",
        max_completion_tokens: int = 1024,
        client: Groq | None = None,
    ):
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_completion_tokens = max_completion_tokens
        # max_retries=1: one retry with backoff on 408/409/429/5xx and connection
        # errors; the SDK waits for retry-after on 429.
        self._client = client or Groq(api_key=api_key, timeout=timeout_s, max_retries=1)
        self.last_usage = None
        self.last_latency_s: float | None = None

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "GroqClient":
        settings = settings or get_settings()
        if settings.llm_api_key is None:
            raise LLMError("LLM_API_KEY is not set. Add your Groq key to .env locally (see .env.example), "
                           "or to the service's variables when deployed.")
        return cls(
            settings.llm_api_key.get_secret_value(),
            settings.llm_model,
            timeout_s=settings.llm_timeout_s,
            reasoning_effort=settings.llm_reasoning_effort,
            max_completion_tokens=settings.llm_max_completion_tokens,
        )

    def _format_options(self, response_schema: dict) -> dict:
        if self.model.startswith(STRICT_JSON_PREFIX):
            return {
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "recommendations", "strict": True, "schema": response_schema},
                },
                "reasoning_effort": self.reasoning_effort,
                "include_reasoning": False,
            }
        # Other models only get JSON mode; the prompt asks for the shape and the parser checks it.
        return {"response_format": {"type": "json_object"}}

    def complete(self, system: str, user: str, response_schema: dict, max_tokens: int | None = None) -> str:
        # The configured cap is a ceiling: a call may ask for less, never more.
        cap = min(max_tokens or self.max_completion_tokens, self.max_completion_tokens)
        start = time.perf_counter()
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_completion_tokens=cap,
                **self._format_options(response_schema),
            )
        except groq.APIError as exc:
            if _is_unusable_reply(exc):
                raise MalformedReplyError("Groq rejected the reply: it was not JSON in the required shape") from exc
            raise LLMError(f"Groq call failed: {type(exc).__name__}: {exc}") from exc
        self.last_latency_s = time.perf_counter() - start

        choice = resp.choices[0]
        self.last_usage = resp.usage
        log.info(
            "llm model=%s latency=%.2fs prompt_tokens=%s completion_tokens=%s finish=%s",
            self.model, self.last_latency_s,
            getattr(resp.usage, "prompt_tokens", None), getattr(resp.usage, "completion_tokens", None),
            choice.finish_reason,
        )
        content = choice.message.content
        if not content or not content.strip():
            raise LLMError(f"Groq returned no content (finish_reason={choice.finish_reason})")
        return content
