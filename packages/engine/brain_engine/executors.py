"""Built-in tool executors.

Stage 2 ships one: :class:`LLMReasoningExecutor`, the default worker for any
plan step that just needs Claude to think. It renders the
``llm_reasoning/v1`` template with the step's payload and returns the
structured response as the step output.
"""

from __future__ import annotations

from typing import Any

from brain_llm.service import LLMService
from brain_llm.types import LLMRequest
from brain_prompts.registry import PromptRegistry

from brain_engine.tool_router import ToolExecutionContext


class LLMReasoningExecutor:
    capability = "llm_reasoning"
    tool_id = "builtin:llm_reasoning/v1"

    def __init__(self, llm: LLMService, prompts: PromptRegistry) -> None:
        self._llm = llm
        self._prompts = prompts

    def execute(self, ctx: ToolExecutionContext) -> dict[str, Any]:
        instruction = _extract_instruction(ctx.input_payload) or ctx.step_name
        rendered = self._prompts.render(
            "llm_reasoning/v1",
            {
                "goal": ctx.goal,
                "step_name": ctx.step_name,
                "instruction": instruction,
            },
        )
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
                f"llm_reasoning returned non-structured output for step {ctx.step_id}"
            )
        return response.parsed


def _extract_instruction(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    for key in ("instruction", "prompt", "task", "query"):
        v = payload.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return None
