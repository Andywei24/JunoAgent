"""High-level LLM service: the one callers import.

Adds retry-on-malformed-output, provider fallback, and structured-output
enforcement on top of a raw provider. Instrumentation hooks (callbacks)
let the engine record ``llm.called`` events + cost without the service
caring about the event store.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from brain_llm.client import LLMClient
from brain_llm.errors import LLMError, MalformedOutputError, ProviderUnavailableError
from brain_llm.types import LLMRequest, LLMResponse


class LLMService:
    def __init__(
        self,
        primary: LLMClient,
        fallbacks: list[LLMClient] | None = None,
        *,
        max_schema_retries: int = 1,
        on_call: Callable[[LLMRequest, LLMResponse], None] | None = None,
    ) -> None:
        self._primary = primary
        self._fallbacks = fallbacks or []
        self._max_schema_retries = max_schema_retries
        self._on_call = on_call

    @property
    def providers(self) -> list[str]:
        return [self._primary.name, *(f.name for f in self._fallbacks)]

    def call(self, request: LLMRequest) -> LLMResponse:
        """Execute a request. Tries schema-retry, then provider fallback."""
        last_error: Exception | None = None

        for provider in (self._primary, *self._fallbacks):
            try:
                response = self._call_with_schema_retry(provider, request)
            except ProviderUnavailableError as exc:
                last_error = exc
                continue
            except LLMError:
                raise
            if self._on_call is not None:
                try:
                    self._on_call(request, response)
                except Exception:
                    # Instrumentation must never block the call path.
                    pass
            return response

        raise ProviderUnavailableError(
            f"All providers unavailable: tried {self.providers}. Last: {last_error!r}"
        )

    def _call_with_schema_retry(
        self, provider: LLMClient, request: LLMRequest
    ) -> LLMResponse:
        attempts = 1 + (self._max_schema_retries if request.response_schema else 0)
        last: Exception | None = None
        active = request
        for i in range(attempts):
            response = provider.call(active)
            if active.response_schema is None:
                return response
            if response.parsed is not None and isinstance(response.parsed, dict):
                return response
            last = MalformedOutputError(
                f"provider={provider.name} attempt={i + 1}: structured output missing"
            )
            active = _nudge_for_structured(active)
        assert last is not None
        raise last


def _nudge_for_structured(request: LLMRequest) -> LLMRequest:
    """Append a brief reminder for providers that don't natively enforce schemas."""
    from dataclasses import replace

    from brain_llm.types import LLMMessage

    reminder = LLMMessage(
        role="user",
        content=(
            "Your previous response was not valid structured JSON matching the "
            "requested schema. Respond with ONLY a JSON object that matches the "
            "schema exactly — no prose, no code fences."
        ),
    )
    return replace(request, messages=[*request.messages, reminder])


# Re-export for convenience
__all__ = ["LLMService"]

# Keep linters happy about unused import in type-only context
_ = Any
