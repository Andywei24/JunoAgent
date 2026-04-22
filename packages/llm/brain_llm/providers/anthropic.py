"""Anthropic (Claude) provider adapter.

The ``anthropic`` SDK is imported lazily so callers that only use the mock
provider don't need to install it.

Routing: ``request.metadata["intent"]`` selects the model tier.

  * ``reasoning``              -> Opus 4.7 (deep multi-step thought)
  * ``structured_extraction``  -> Haiku 4.5 (cheap JSON shaping)
  * anything else / missing    -> Sonnet 4.6 (workhorse default)

An explicit ``request.model`` overrides routing.

Structured output uses ``output_config.format = {type: "json_schema", ...}``
when ``request.response_schema`` is set. This is the GA mechanism and is
preferred over tool-use forcing.

Prompt caching: the last system block gets ``cache_control: ephemeral`` so
repeated calls during a task reuse the prefix.

Rate limits and 5xx are translated to :class:`ProviderUnavailableError` so
:class:`LLMService` can fall through to a configured fallback provider.
"""

from __future__ import annotations

import json
import os
from typing import Any

from brain_llm.errors import LLMError, ProviderUnavailableError
from brain_llm.types import LLMRequest, LLMResponse, TokenUsage


# Per-million-token pricing, USD. Updated 2026-04.
_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

_INTENT_MODEL: dict[str, str] = {
    "reasoning": "claude-opus-4-7",
    "structured_extraction": "claude-haiku-4-5",
}
_DEFAULT_MODEL = "claude-sonnet-4-6"

# Opus 4.7 removed temperature/top_p/top_k and only supports adaptive thinking.
_OPUS_47 = "claude-opus-4-7"


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        default_model: str | None = None,
        effort: str = "high",
    ) -> None:
        # Lazy import so the dep is optional.
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:
            raise ProviderUnavailableError(
                "anthropic SDK not installed. `pip install anthropic` to enable."
            ) from exc

        key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderUnavailableError(
                "ANTHROPIC_API_KEY is not set; cannot construct Anthropic provider."
            )

        from anthropic import Anthropic

        self._client = Anthropic(api_key=key)
        self._default_model = default_model or _DEFAULT_MODEL
        self._effort = effort

    def _pick_model(self, request: LLMRequest) -> str:
        if request.model:
            return request.model
        intent = request.metadata.get("intent")
        if isinstance(intent, str) and intent in _INTENT_MODEL:
            return _INTENT_MODEL[intent]
        return self._default_model

    def _build_payload(self, request: LLMRequest, model: str) -> dict[str, Any]:
        system_blocks: list[dict[str, Any]] = []
        turns: list[dict[str, Any]] = []
        for msg in request.messages:
            if msg.role == "system":
                system_blocks.append({"type": "text", "text": msg.content})
            else:
                turns.append({"role": msg.role, "content": msg.content})

        # Cache the stable system prefix. Harmless if under the min token bar.
        if system_blocks:
            system_blocks[-1]["cache_control"] = {"type": "ephemeral"}

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": request.max_tokens,
            "messages": turns,
        }
        if system_blocks:
            payload["system"] = system_blocks

        # Opus 4.7 rejects sampling params; skip them there. For other models,
        # adaptive thinking + explicit temperature don't conflict.
        if model != _OPUS_47:
            payload["temperature"] = request.temperature

        # Adaptive thinking is the current recommendation on 4.6 / 4.7 tiers.
        if model.startswith(("claude-opus-4-", "claude-sonnet-4-6")):
            payload["thinking"] = {"type": "adaptive"}

        output_config: dict[str, Any] = {"effort": self._effort}
        if request.response_schema is not None:
            output_config["format"] = {
                "type": "json_schema",
                "schema": request.response_schema,
            }
        payload["output_config"] = output_config

        return payload

    def call(self, request: LLMRequest) -> LLMResponse:
        import anthropic

        model = self._pick_model(request)
        payload = self._build_payload(request, model)

        try:
            response = self._client.messages.create(**payload)
        except anthropic.RateLimitError as exc:
            raise ProviderUnavailableError(f"anthropic rate-limited: {exc}") from exc
        except anthropic.APIStatusError as exc:
            # 5xx => treat as transient; 4xx bubbles up as a real error.
            status = getattr(exc, "status_code", None)
            if status is not None and 500 <= status < 600:
                raise ProviderUnavailableError(
                    f"anthropic {status}: {exc}"
                ) from exc
            raise LLMError(f"anthropic API error: {exc}") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderUnavailableError(
                f"anthropic connection error: {exc}"
            ) from exc

        text_parts: list[str] = []
        for block in response.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(block.text)
        text = "".join(text_parts)

        parsed: dict[str, Any] | None = None
        if request.response_schema is not None and text:
            try:
                loaded = json.loads(text)
                if isinstance(loaded, dict):
                    parsed = loaded
            except json.JSONDecodeError:
                parsed = None  # service layer will retry with a nudge.

        input_tokens = getattr(response.usage, "input_tokens", 0) or 0
        output_tokens = getattr(response.usage, "output_tokens", 0) or 0
        in_price, out_price = _PRICING.get(model, (0.0, 0.0))
        cost = (input_tokens * in_price + output_tokens * out_price) / 1_000_000

        return LLMResponse(
            text=text,
            parsed=parsed,
            model=model,
            provider=self.name,
            usage=TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=round(cost, 6),
            ),
            raw={"id": getattr(response, "id", None), "stop_reason": getattr(response, "stop_reason", None)},
        )
