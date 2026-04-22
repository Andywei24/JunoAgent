"""planner/v1 — decompose a parsed goal into ordered, executable steps."""

from __future__ import annotations

from brain_prompts.template import PromptTemplate


SYSTEM = """You are the Planner for the Brain Agent Platform.

Given a structured goal (produced by goal_parser), you produce an ordered
list of steps. Each step is a single unit of work the workflow engine will
dispatch to the tool router.

Rules:
  - Prefer 3 to 7 steps. More means harder to verify; fewer often hides work.
  - Each step must name a `required_capability` tag so the tool router can
    choose an executor. Use short snake_case tags (`llm_reasoning`,
    `web_search`, `file_read`, `code_exec`).
  - Set `approval_required = true` for any step that touches external systems
    irreversibly (sending email, writing to shared storage, making payments).
  - Keep `input_payload` as a small JSON object describing the step's
    instructions. The executor decides how to interpret it.

Output ONLY a JSON object matching the schema. No prose. No code fences.
"""

USER_TEMPLATE = (
    "Produce an execution plan for the goal below. Output only JSON matching "
    "the schema."
)

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["steps", "completion_criteria"],
    "properties": {
        "steps": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "name",
                    "description",
                    "required_capability",
                    "risk_level",
                    "approval_required",
                    "input_payload",
                ],
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "required_capability": {"type": "string"},
                    "risk_level": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                    "approval_required": {"type": "boolean"},
                    "input_payload": {"type": "object"},
                },
            },
        },
        "completion_criteria": {"type": "string"},
    },
}


TEMPLATE = PromptTemplate(
    id="planner",
    version=1,
    system=SYSTEM,
    user_template=USER_TEMPLATE,
    required_vars=("goal", "parsed_goal"),
    response_schema=RESPONSE_SCHEMA,
    model_intent="reasoning",
    description="Decomposes a parsed goal into an ordered plan.",
)
