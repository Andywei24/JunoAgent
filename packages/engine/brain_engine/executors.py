"""Built-in tool executors.

Each executor pairs a :class:`ToolSpec` (the declared contract) with an
``execute`` method that renders a prompt and calls the LLM. The registry of
executors + their specs is the source of truth for the ``tools`` table.
"""

from __future__ import annotations

from typing import Any

from brain_core.enums import RiskLevel, ToolBackendType, ToolCapabilityType
from brain_llm.service import LLMService
from brain_llm.types import LLMRequest
from brain_prompts.registry import PromptRegistry

from brain_engine.tool_router import ToolExecutionContext
from brain_engine.tool_spec import ToolSpec


class _LLMBackedExecutor:
    """Shared plumbing for executors that render a prompt and return parsed JSON."""

    spec: ToolSpec
    prompt_id: str

    def __init__(self, llm: LLMService, prompts: PromptRegistry) -> None:
        self._llm = llm
        self._prompts = prompts

    def _render_variables(self, ctx: ToolExecutionContext) -> dict[str, Any]:
        raise NotImplementedError

    def execute(self, ctx: ToolExecutionContext) -> dict[str, Any]:
        rendered = self._prompts.render(self.prompt_id, self._render_variables(ctx))
        request = LLMRequest(
            messages=rendered.messages,
            response_schema=rendered.response_schema,
            metadata={
                "prompt_id": rendered.prompt_id_versioned,
                "intent": rendered.model_intent,
                "task_id": ctx.task_id,
                "step_id": ctx.step_id,
            },
        )
        response = self._llm.call(request)
        if response.parsed is None:
            raise RuntimeError(
                f"{self.spec.id} returned non-structured output for step {ctx.step_id}"
            )
        return response.parsed


class LLMReasoningExecutor(_LLMBackedExecutor):
    prompt_id = "llm_reasoning/v1"
    spec = ToolSpec(
        id="tool_llm_reasoning",
        name="llm_reasoning",
        description="General-purpose reasoning worker backed by the platform LLM.",
        capability="llm_reasoning",
        capability_type=ToolCapabilityType.REASONING,
        backend_type=ToolBackendType.LLM,
        risk_level=RiskLevel.LOW,
        version="1",
        timeout_seconds=60,
        input_schema={
            "type": "object",
            "properties": {
                "instruction": {"type": "string"},
                "prompt": {"type": "string"},
                "task": {"type": "string"},
                "query": {"type": "string"},
            },
        },
        output_schema={
            "type": "object",
            "required": ["summary", "details"],
            "properties": {
                "summary": {"type": "string"},
                "details": {"type": "string"},
            },
        },
    )

    def _render_variables(self, ctx: ToolExecutionContext) -> dict[str, Any]:
        instruction = _extract_instruction(ctx.input_payload) or ctx.step_name
        return {
            "goal": ctx.goal,
            "step_name": ctx.step_name,
            "instruction": instruction,
        }


class SummarizeTextExecutor(_LLMBackedExecutor):
    prompt_id = "summarize_text/v1"
    spec = ToolSpec(
        id="tool_summarize_text",
        name="summarize_text",
        description="Summarize a body of text into one paragraph plus bullet highlights.",
        capability="summarize_text",
        capability_type=ToolCapabilityType.SUMMARIZATION,
        backend_type=ToolBackendType.LLM,
        risk_level=RiskLevel.LOW,
        version="1",
        timeout_seconds=60,
        input_schema={
            "type": "object",
            "required": ["text"],
            "properties": {
                "text": {"type": "string"},
                "focus": {"type": "string"},
            },
        },
        output_schema={
            "type": "object",
            "required": ["summary", "highlights"],
            "properties": {
                "summary": {"type": "string"},
                "highlights": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
    )

    def _render_variables(self, ctx: ToolExecutionContext) -> dict[str, Any]:
        payload = ctx.input_payload or {}
        text = payload.get("text") or _extract_instruction(payload) or ctx.step_name
        return {
            "goal": ctx.goal,
            "step_name": ctx.step_name,
            "text": text,
            "focus": payload.get("focus") or "general summary",
        }


class CompareItemsExecutor(_LLMBackedExecutor):
    prompt_id = "compare_items/v1"
    spec = ToolSpec(
        id="tool_compare_items",
        name="compare_items",
        description="Compare two or more items across caller-specified criteria.",
        capability="compare_items",
        capability_type=ToolCapabilityType.COMPARISON,
        backend_type=ToolBackendType.LLM,
        risk_level=RiskLevel.LOW,
        version="1",
        timeout_seconds=60,
        input_schema={
            "type": "object",
            "required": ["items"],
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "criteria": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
        output_schema={
            "type": "object",
            "required": ["summary", "comparisons", "recommendation"],
            "properties": {
                "summary": {"type": "string"},
                "comparisons": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["item", "notes"],
                        "properties": {
                            "item": {"type": "string"},
                            "notes": {"type": "string"},
                        },
                    },
                },
                "recommendation": {"type": "string"},
            },
        },
    )

    def _render_variables(self, ctx: ToolExecutionContext) -> dict[str, Any]:
        payload = ctx.input_payload or {}
        items = payload.get("items") or []
        criteria = payload.get("criteria") or ["clarity", "tradeoffs"]
        return {
            "goal": ctx.goal,
            "step_name": ctx.step_name,
            "items": items,
            "criteria": criteria,
        }


def _extract_instruction(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    for key in ("instruction", "prompt", "task", "query"):
        v = payload.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return None
