"""planner/v1 — decompose a parsed goal into ordered, executable steps."""

from __future__ import annotations

from brain_prompts.template import PromptTemplate


SYSTEM = """You are the Planner for the Brain Agent Platform.

Given a structured goal (produced by goal_parser), you produce an ordered
list of steps. Each step is a single unit of work the workflow engine will
dispatch to the tool router.

Rules:
  - Prefer 3 to 7 steps. More means harder to verify; fewer often hides work.
  - Each step must name a `required_capability` — pick a value that appears
    in the capabilities list provided in the user message. Using a capability
    not in that list will fail routing and block the task.
  - Assign `risk_level` based on the worst outcome of the step:
      * `low`      — pure reasoning, read-only lookups, local scratch work.
      * `medium`   — reversible writes to user-private scratch space, or any
                     external call whose output is consumed only by later
                     steps (web search, data retrieval).
      * `high`     — reversible writes to shared systems, partial send-style
                     actions, anything a human would want to double-check.
      * `critical` — irreversible, externally-visible actions: sending
                     email, posting, making payments, deleting data, any
                     action that cannot be rolled back by the agent alone.
  - Set `approval_required = true` whenever the step touches external
    systems irreversibly, or its `risk_level` is `high` or `critical`. When
    in doubt, err toward requiring approval — a paused task is cheaper than
    a bad action.
  - Never propose a capability whose tool risk exceeds the step work: if
    the capability list marks a tool as `high`, the step that uses it
    inherits at least that risk.
  - Keep `input_payload` as a small JSON object describing the step's
    instructions. The executor decides how to interpret it.

Output ONLY a JSON object matching the schema. No prose. No code fences.
"""

USER_TEMPLATE = (
    "Available capabilities (id · capability · tool_risk):\n"
    "{capabilities}\n\n"
    "Produce an execution plan for the goal below. Output only JSON "
    "matching the schema."
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
                        "enum": ["low", "medium", "high", "critical"],
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
    required_vars=("goal", "parsed_goal", "capabilities"),
    response_schema=RESPONSE_SCHEMA,
    model_intent="reasoning",
    description="Decomposes a parsed goal into an ordered plan.",
)
