"""Provider-neutral LLM interface, so the engine and tests never import a provider SDK."""

from typing import Protocol


class LLMError(RuntimeError):
    """The model call failed, or returned nothing usable."""


class MalformedReplyError(LLMError):
    """The provider rejected the model's reply for not matching the schema. Worth one retry."""


class LLMClient(Protocol):
    def complete(self, system: str, user: str, response_schema: dict, max_tokens: int | None = None) -> str:
        """Return the model's raw text reply. Raise LLMError on failure.

        `max_tokens` caps the reply; None means the client's own limit."""
        ...
