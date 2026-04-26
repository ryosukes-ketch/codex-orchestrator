from abc import ABC, abstractmethod
from typing import Any


class LLMClient(ABC):
    """Minimal interface for synchronous LLM text completion."""

    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """Return the model's text response given a system and user prompt."""

    def pop_last_call_metadata(self) -> dict[str, Any]:
        """Return best-effort metadata for the latest completion call.

        Implementations can expose transport/provider details (for example,
        gateway endpoint, fallback usage, HTTP status, or error kind). The
        default implementation returns an empty map for clients that do not
        support call-level metadata.
        """

        return {}
