"""goal_parser/v1 — turn a raw user goal into a structured task definition."""

from __future__ import annotations

from brain_prompts.template import PromptTemplate


SYSTEM = """You are the Goal Parser for the Brain Agent Platform.

Your job is to read a raw user goal and transform it into a structured task
definition that downstream components (planner, workflow engine, tool router)
can act on deterministically.

Respond with ONLY a JSON object matching the requested schema. No prose. No
code fences. The object must be safe to feed directly into an automated
planner.

Guidelines:
  - Keep `objective` one sentence, imperative.
  - `deliverable` is what the user will see at the end.
  - `candidate_capabilities` lists capability tags you expect will be needed
    (e.g. `llm_reasoning`, `web_search`). Only include what's likely relevant.
  - `assumptions` are things you had to guess; keep them honest and short.
"""

USER_TEMPLATE = (
    "Parse the following goal into a structured task definition. Output only "
    "JSON matching the schema."
)

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "objective",
        "deliverable",
        "scope",
        "input_type",
        "risk_level",
        "candidate_capabilities",
        "assumptions",
    ],
    "properties": {
        "objective": {"type": "string"},
        "deliverable": {"type": "string"},
        "scope": {"type": "string"},
        "input_type": {"type": "string"},
        "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
        "candidate_capabilities": {
            "type": "array",
            "items": {"type": "string"},
        },
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
}


TEMPLATE = PromptTemplate(
    id="goal_parser",
    version=1,
    system=SYSTEM,
    user_template=USER_TEMPLATE,
    required_vars=("goal",),
    response_schema=RESPONSE_SCHEMA,
    model_intent="structured_extraction",
    description="Parses a raw user goal into a structured task definition.",
)
