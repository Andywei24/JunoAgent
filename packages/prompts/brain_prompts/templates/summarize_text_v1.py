"""summarize_text/v1 — condenses a body of text into a paragraph + highlights."""

from __future__ import annotations

from brain_prompts.template import PromptTemplate


SYSTEM = """You are the Summarizer for the Brain Agent Platform.

Given a body of text and an optional focus, produce a one-paragraph summary
and 2-5 short highlight bullets. Stay faithful to the source; do not invent
facts. Output ONLY JSON matching the schema.
"""

USER_TEMPLATE = (
    "Summarize the text below. Keep the summary tight (2-4 sentences) and "
    "the highlights punchy. Output only JSON matching the schema."
)

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "highlights"],
    "properties": {
        "summary": {"type": "string"},
        "highlights": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string"},
        },
    },
}


TEMPLATE = PromptTemplate(
    id="summarize_text",
    version=1,
    system=SYSTEM,
    user_template=USER_TEMPLATE,
    required_vars=("goal", "step_name", "text", "focus"),
    response_schema=RESPONSE_SCHEMA,
    model_intent="structured_extraction",
    description="Executor for capability=summarize_text.",
)
