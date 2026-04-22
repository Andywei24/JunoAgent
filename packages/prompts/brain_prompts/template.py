"""Prompt template primitives.

A :class:`PromptTemplate` is a versioned description of how to build the
``system`` / ``user`` messages for a specific reasoning task. It records:

  * ``id``              — logical identifier (``"planner"``)
  * ``version``         — monotonically increasing, tracked for cache keys
  * ``system``          — stable system prompt (good cache hit target)
  * ``user_template``   — formatted with ``variables`` into the user message
  * ``required_vars``   — enforced at render time
  * ``response_schema`` — optional JSON schema for structured output
  * ``model_intent``    — routing hint consumed by the LLM provider

Variables are injected into the user message by simple ``{name}`` substitution
and echoed back into bracketed fences (``[name]\\n...\\n[/name]``). The
fences give the mock provider and, more importantly, future debug tooling an
unambiguous way to extract what the model was shown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from brain_llm.types import LLMMessage


@dataclass(slots=True, frozen=True)
class RenderedPrompt:
    """A template fully realized against a set of variables."""

    prompt_id: str
    version: int
    messages: list[LLMMessage]
    response_schema: dict[str, Any] | None
    model_intent: str | None

    @property
    def prompt_id_versioned(self) -> str:
        return f"{self.prompt_id}/v{self.version}"


@dataclass(slots=True)
class PromptTemplate:
    id: str
    version: int
    system: str
    user_template: str
    required_vars: tuple[str, ...] = ()
    response_schema: dict[str, Any] | None = None
    model_intent: str | None = None
    description: str = ""

    @property
    def prompt_id(self) -> str:
        return f"{self.id}/v{self.version}"

    def render(self, variables: dict[str, Any] | None = None) -> RenderedPrompt:
        vars_ = dict(variables or {})
        missing = [k for k in self.required_vars if k not in vars_ or vars_[k] is None]
        if missing:
            raise KeyError(
                f"prompt {self.prompt_id} missing required variables: {missing}"
            )

        fenced_blocks = "\n\n".join(
            f"[{k}]\n{_stringify(vars_[k])}\n[/{k}]" for k in self.required_vars
        )

        try:
            user_body = self.user_template.format(**vars_)
        except KeyError as exc:
            raise KeyError(
                f"prompt {self.prompt_id} user_template references undefined variable: {exc}"
            ) from exc

        user_message = (
            f"{user_body}\n\n{fenced_blocks}" if fenced_blocks else user_body
        )
        messages = [
            LLMMessage(role="system", content=self.system),
            LLMMessage(role="user", content=user_message),
        ]
        return RenderedPrompt(
            prompt_id=self.id,
            version=self.version,
            messages=messages,
            response_schema=self.response_schema,
            model_intent=self.model_intent,
        )


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    import json as _json

    return _json.dumps(value, ensure_ascii=False, indent=2, default=str)


__all__ = ["PromptTemplate", "RenderedPrompt"]
