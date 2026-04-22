"""llm_reasoning/v1 — the default executor for plan steps with `llm_reasoning`."""

from __future__ import annotations

from brain_prompts.template import PromptTemplate


SYSTEM = """You are a reasoning worker for the Brain Agent Platform.

You receive a single plan step and produce a focused answer for that step
alone. You are not the orchestrator — do not try to plan, branch, or call
tools. Just think through the step's instruction and return your result.

Output ONLY a JSON object matching the schema. Keep `summary` one sentence.
Put the substance in `details`.
"""

USER_TEMPLATE = (
    "Execute the step described below. Use the goal as context but focus on "
    "the step's instruction. Output only JSON matching the schema."
)

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "details"],
    "properties": {
        "summary": {"type": "string"},
        "details": {"type": "string"},
    },
}


TEMPLATE = PromptTemplate(
    id="llm_reasoning",
    version=1,
    system=SYSTEM,
    user_template=USER_TEMPLATE,
    required_vars=("goal", "step_name", "instruction"),
    response_schema=RESPONSE_SCHEMA,
    model_intent="reasoning",
    description="Default executor for plan steps with capability=llm_reasoning.",
)
