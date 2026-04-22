"""compare_items/v1 — compares a small set of items across caller criteria."""

from __future__ import annotations

from brain_prompts.template import PromptTemplate


SYSTEM = """You are the Comparator for the Brain Agent Platform.

Given 2-6 items and optional criteria, compare them briefly and recommend
one. Do not invent features that were not stated; if information is missing,
say so in the notes. Output ONLY JSON matching the schema.
"""

USER_TEMPLATE = (
    "Compare the items below against the given criteria. Return a short "
    "note per item plus a single recommendation. Output only JSON."
)

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "comparisons", "recommendation"],
    "properties": {
        "summary": {"type": "string"},
        "comparisons": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["item", "notes"],
                "properties": {
                    "item": {"type": "string"},
                    "notes": {"type": "string"},
                },
            },
        },
        "recommendation": {"type": "string"},
    },
}


TEMPLATE = PromptTemplate(
    id="compare_items",
    version=1,
    system=SYSTEM,
    user_template=USER_TEMPLATE,
    required_vars=("goal", "step_name", "items", "criteria"),
    response_schema=RESPONSE_SCHEMA,
    model_intent="reasoning",
    description="Executor for capability=compare_items.",
)
