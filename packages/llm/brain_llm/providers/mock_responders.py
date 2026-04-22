"""Canned responders for the stage-2 prompt library.

Kept in a separate module so the mock provider stays generic — other projects
or test suites can swap in a different responder set without touching the
provider itself.
"""

from __future__ import annotations

import re
from typing import Any

from brain_llm.types import LLMRequest


def _first_var(request: LLMRequest, key: str) -> str | None:
    """Best-effort extraction of a named variable from an assembled prompt.

    Our ``brain_prompts`` runtime emits fenced blocks like ``[goal]\\n...\\n[/goal]``
    in the user message; this helper pulls the content back out. Strict
    template-aware parsing would be over-engineering for a mock.
    """
    pattern = re.compile(rf"\[{re.escape(key)}\]\n(.*?)\n\[/{re.escape(key)}\]", re.DOTALL)
    for msg in request.messages:
        m = pattern.search(msg.content)
        if m:
            return m.group(1).strip()
    return None


def goal_parser_v1(request: LLMRequest) -> dict[str, Any]:
    goal = _first_var(request, "goal") or "unknown goal"
    short = goal[:120]
    return {
        "objective": f"Address the user's goal: {short}",
        "deliverable": "A concise synthesized answer with supporting reasoning.",
        "scope": "single self-contained run",
        "input_type": "text",
        "risk_level": "low",
        "candidate_capabilities": ["llm_reasoning"],
        "assumptions": [
            "no external data sources required",
            "user will accept a reasoned answer without tool use",
        ],
    }


def planner_v1(request: LLMRequest) -> dict[str, Any]:
    goal = _first_var(request, "goal") or "unknown goal"
    short = goal[:120]
    return {
        "steps": [
            {
                "name": "Restate and decompose the goal",
                "description": (
                    "Read the user's goal and decompose it into the key questions or "
                    f"sub-problems that need answers. Goal: {short}"
                ),
                "required_capability": "llm_reasoning",
                "risk_level": "low",
                "approval_required": False,
                "input_payload": {"instruction": "decompose_goal"},
            },
            {
                "name": "Compare the main options",
                "description": (
                    "Identify 2-3 concrete options implied by the goal and compare "
                    "them across clarity and tradeoffs."
                ),
                "required_capability": "compare_items",
                "risk_level": "low",
                "approval_required": False,
                "input_payload": {
                    "items": ["option_a", "option_b"],
                    "criteria": ["clarity", "tradeoffs"],
                },
            },
            {
                "name": "Summarize the draft answer",
                "description": "Produce a one-paragraph summary with 3 highlights.",
                "required_capability": "summarize_text",
                "risk_level": "low",
                "approval_required": False,
                "input_payload": {
                    "text": f"Draft answer addressing the goal: {short}",
                    "focus": "user-facing takeaways",
                },
            },
        ],
        "completion_criteria": "A finalized answer with comparison + summary is produced.",
    }


def llm_reasoning_v1(request: LLMRequest) -> dict[str, Any]:
    instruction = _first_var(request, "instruction") or "respond"
    step_name = _first_var(request, "step_name") or "reasoning step"
    goal = _first_var(request, "goal") or ""
    return {
        "summary": f"[mock] completed '{step_name}' ({instruction}).",
        "details": (
            f"Mock reasoning output for step '{step_name}'. "
            f"Original goal snippet: {goal[:80]}"
        ),
    }


def summarize_text_v1(request: LLMRequest) -> dict[str, Any]:
    text = _first_var(request, "text") or ""
    focus = _first_var(request, "focus") or "general"
    snippet = text[:120]
    return {
        "summary": (
            f"[mock] Summary focused on {focus}. Source snippet: {snippet}"
        ),
        "highlights": [
            "[mock] highlight #1",
            "[mock] highlight #2",
            "[mock] highlight #3",
        ],
    }


def compare_items_v1(request: LLMRequest) -> dict[str, Any]:
    raw_items = _first_var(request, "items") or "[]"
    try:
        import json as _json

        items = _json.loads(raw_items) if raw_items.startswith("[") else [raw_items]
    except Exception:
        items = [raw_items]
    if not items:
        items = ["option_a", "option_b"]
    return {
        "summary": f"[mock] Compared {len(items)} items.",
        "comparisons": [
            {"item": str(item), "notes": f"[mock] notes for {item}"}
            for item in items
        ],
        "recommendation": f"[mock] Pick {items[0]}.",
    }


DEFAULT_RESPONDERS = {
    "goal_parser/v1": goal_parser_v1,
    "planner/v1": planner_v1,
    "llm_reasoning/v1": llm_reasoning_v1,
    "summarize_text/v1": summarize_text_v1,
    "compare_items/v1": compare_items_v1,
}
