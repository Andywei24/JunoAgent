"""Tool router — resolves capability tags to concrete executors.

The router is the boundary between plan steps (which carry a
``required_capability`` string) and the code that actually does the work.
Each executor carries a :class:`ToolSpec` so the router can surface its
declared id, risk level, and schemas without the executor leaking
implementation details.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from brain_engine.tool_spec import ToolSpec


@dataclass(slots=True)
class ToolExecutionContext:
    task_id: str
    step_id: str
    goal: str
    step_name: str
    input_payload: dict[str, Any]


class ToolExecutor(Protocol):
    spec: ToolSpec

    def execute(self, ctx: ToolExecutionContext) -> dict[str, Any]:
        ...


class ToolRouter:
    def __init__(self) -> None:
        self._by_capability: dict[str, ToolExecutor] = {}

    def register(self, executor: ToolExecutor) -> None:
        cap = executor.spec.capability
        if cap in self._by_capability:
            raise ValueError(f"capability already registered: {cap}")
        self._by_capability[cap] = executor

    def resolve(self, capability: str | None) -> ToolExecutor:
        """Return an executor for ``capability``, falling back to ``llm_reasoning``.

        The fallback is deliberate: plans are LLM-authored and the model
        occasionally invents capability tags. Routing unknowns to general
        reasoning keeps the run alive; policy gates in later stages will
        tighten this when stakes are high.
        """
        if capability and capability in self._by_capability:
            return self._by_capability[capability]
        if "llm_reasoning" in self._by_capability:
            return self._by_capability["llm_reasoning"]
        raise KeyError(
            f"no executor for capability={capability!r} and no llm_reasoning fallback"
        )

    def capabilities(self) -> list[str]:
        return sorted(self._by_capability.keys())

    def list_specs(self) -> list[ToolSpec]:
        return [e.spec for e in self._by_capability.values()]
