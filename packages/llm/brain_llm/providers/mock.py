"""Deterministic in-memory provider.

Used for:
  * Local dev without API keys.
  * The Stage 2 verification script — canned responses mean the end-to-end
    loop is reproducible without a live model.
  * Future unit tests that want predictable outputs.

Responders are looked up by the ``prompt_id`` metadata the engine attaches to
every request. An unknown prompt returns a degraded echo response so missing
wiring surfaces loudly rather than silently producing junk.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from brain_llm.client import LLMClient
from brain_llm.types import LLMRequest, LLMResponse, TokenUsage


Responder = Callable[[LLMRequest], dict[str, Any]]


class MockLLMProvider:
    name = "mock"

    def __init__(self, responders: dict[str, Responder] | None = None) -> None:
        self._responders: dict[str, Responder] = dict(responders or {})

    def register(self, prompt_id: str, fn: Responder) -> None:
        self._responders[prompt_id] = fn

    def call(self, request: LLMRequest) -> LLMResponse:
        prompt_id = request.metadata.get("prompt_id")
        responder = self._responders.get(prompt_id) if prompt_id else None

        if responder is not None:
            parsed = responder(request)
        elif request.response_schema is not None:
            parsed = {"note": f"mock: no responder registered for prompt_id={prompt_id!r}"}
        else:
            # Free-text echo — good enough for smoke tests.
            user_last = next(
                (m.content for m in reversed(request.messages) if m.role == "user"), ""
            )
            return LLMResponse(
                text=f"[mock] received: {user_last[:200]}",
                parsed=None,
                model=request.model or "mock-echo",
                provider=self.name,
                usage=TokenUsage(input_tokens=0, output_tokens=0, cost_usd=0.0),
                raw={},
            )

        text = json.dumps(parsed, ensure_ascii=False)
        return LLMResponse(
            text=text,
            parsed=parsed,
            model=request.model or "mock-structured",
            provider=self.name,
            usage=TokenUsage(input_tokens=0, output_tokens=0, cost_usd=0.0),
            raw={"prompt_id": prompt_id},
        )


# Convenience: a ready-to-use provider with stage-2 defaults.
def build_default_mock() -> MockLLMProvider:
    from brain_llm.providers.mock_responders import DEFAULT_RESPONDERS

    return MockLLMProvider(DEFAULT_RESPONDERS)
