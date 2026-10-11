"""Provider-neutral LLM interface, so the engine and tests never import a provider SDK."""

from typing import Protocol


class LLMError(RuntimeError):
    """The model call failed, or returned nothing usable."""


class LLMClient(Protocol):
    def complete(self, system: str, user: str, response_schema: dict) -> str:
        """Return the model's raw text reply. Raise LLMError on failure."""
        ...
