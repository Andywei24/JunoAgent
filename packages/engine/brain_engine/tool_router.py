"""Tool router — maps capability tags to executors.

Stage 2 ships a single built-in executor: ``llm_reasoning``. Later stages
add external tools (web search, code exec) by registering their own
:class:`ToolExecutor` implementations.

The router stays deliberately thin — capability resolution only. Credential
checks, risk gating, and approval flows live in the workflow engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class ToolExecutionContext:
    task_id: str
    step_id: str
    goal: str
    step_name: str
    input_payload: dict[str, Any]


class ToolExecutor(Protocol):
    capability: str
    tool_id: str  # logical identifier recorded on the step

    def execute(self, ctx: ToolExecutionContext) -> dict[str, Any]:
        ...


class ToolRouter:
    def __init__(self) -> None:
        self._by_capability: dict[str, ToolExecutor] = {}

    def register(self, executor: ToolExecutor) -> None:
        cap = executor.capability
        if cap in self._by_capability:
            raise ValueError(f"capability already registered: {cap}")
        self._by_capability[cap] = executor

    def resolve(self, capability: str | None) -> ToolExecutor:
        """Pick an executor for the step. Falls back to ``llm_reasoning``.

        The fallback is deliberate: stage-2 plans are LLM-authored and the
        model sometimes invents capability tags. Rather than failing the step,
        we run it through general reasoning. Later stages will tighten this.
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
