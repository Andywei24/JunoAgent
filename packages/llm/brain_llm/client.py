"""Provider protocol.

A provider maps the platform's ``LLMRequest`` onto whatever the upstream SDK
wants and returns a normalized ``LLMResponse``. Providers should *not* retry
or do schema validation — that belongs in ``LLMService``.
"""

from __future__ import annotations

from typing import Protocol

from brain_llm.types import LLMRequest, LLMResponse


class LLMClient(Protocol):
    name: str

    def call(self, request: LLMRequest) -> LLMResponse:  # pragma: no cover - protocol
        ...
