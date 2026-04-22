"""Typed request + response envelope used by every LLM provider.

Shape intentionally stays narrower than any provider's full API — this is the
contract the engine depends on. New provider features (thinking, caching,
tool use, streaming) belong inside the provider adapter, translated into the
fields here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Role = Literal["system", "user", "assistant"]


@dataclass(slots=True)
class LLMMessage:
    role: Role
    content: str


@dataclass(slots=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(slots=True)
class LLMRequest:
    """A single model call.

    ``response_schema``: when provided, the provider is expected to return
    a structured object matching this JSON schema — Anthropic uses tool-use,
    the mock provider matches canned responders, any future provider either
    enforces it natively or falls back to "reply with JSON" prompting.
    """

    messages: list[LLMMessage]
    model: str | None = None
    max_tokens: int = 2048
    temperature: float = 0.2
    response_schema: dict[str, Any] | None = None
    # Free-form hints for the service layer (prompt_id, task_id, step_id, etc.)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LLMResponse:
    text: str
    parsed: dict[str, Any] | None
    model: str
    provider: str
    usage: TokenUsage
    raw: dict[str, Any] = field(default_factory=dict)
