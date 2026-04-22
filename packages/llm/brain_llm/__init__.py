"""Brain LLM service: provider abstraction + high-level ``LLMService``.

Everything model-facing flows through this package. The Orchestrator, Goal
Parser, Planner, and built-in tools call ``LLMService.call``; provider SDKs
live behind ``LLMClient`` implementations so swapping models never ripples
into the engine.
"""

from brain_llm.errors import (
    LLMError,
    MalformedOutputError,
    ProviderUnavailableError,
)
from brain_llm.service import LLMService
from brain_llm.types import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    TokenUsage,
)

__all__ = [
    "LLMError",
    "LLMMessage",
    "LLMRequest",
    "LLMResponse",
    "LLMService",
    "MalformedOutputError",
    "ProviderUnavailableError",
    "TokenUsage",
]
