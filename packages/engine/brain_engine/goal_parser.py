"""Goal parser: raw goal string -> structured :class:`ParsedGoal`."""

from __future__ import annotations

from typing import Any

from brain_llm.service import LLMService
from brain_llm.types import LLMRequest
from brain_prompts.registry import PromptRegistry


class GoalParser:
    def __init__(self, llm: LLMService, prompts: PromptRegistry) -> None:
        self._llm = llm
        self._prompts = prompts

    def parse(self, goal: str, *, task_id: str) -> dict[str, Any]:
        rendered = self._prompts.render("goal_parser/v1", {"goal": goal})
        request = LLMRequest(
            messages=rendered.messages,
            response_schema=rendered.response_schema,
            metadata={
                "prompt_id": rendered.prompt_id_versioned,
                "intent": rendered.model_intent,
                "task_id": task_id,
            },
        )
        response = self._llm.call(request)
        if response.parsed is None:
            raise RuntimeError(
                f"goal_parser returned non-structured output for task {task_id}"
            )
        return response.parsed
