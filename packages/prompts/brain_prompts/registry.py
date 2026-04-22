"""In-process prompt registry.

The engine talks to the registry — never directly to a template file — so
templates can be swapped, A/B tested, or loaded from a database later
without changing call sites.
"""

from __future__ import annotations

from brain_prompts.template import PromptTemplate, RenderedPrompt


class PromptNotFoundError(KeyError):
    """Raised when a caller asks for a template id that isn't registered."""


class PromptRegistry:
    def __init__(self) -> None:
        self._templates: dict[str, PromptTemplate] = {}

    def register(self, template: PromptTemplate) -> None:
        key = template.prompt_id
        if key in self._templates:
            raise ValueError(f"prompt already registered: {key}")
        self._templates[key] = template

    def get(self, prompt_id: str) -> PromptTemplate:
        try:
            return self._templates[prompt_id]
        except KeyError as exc:
            raise PromptNotFoundError(prompt_id) from exc

    def render(self, prompt_id: str, variables: dict | None = None) -> RenderedPrompt:
        return self.get(prompt_id).render(variables)

    def list_ids(self) -> list[str]:
        return sorted(self._templates.keys())


def default_registry() -> PromptRegistry:
    from brain_prompts.templates.compare_items_v1 import TEMPLATE as _compare
    from brain_prompts.templates.goal_parser_v1 import TEMPLATE as _goal
    from brain_prompts.templates.llm_reasoning_v1 import TEMPLATE as _reason
    from brain_prompts.templates.planner_v1 import TEMPLATE as _planner
    from brain_prompts.templates.summarize_text_v1 import TEMPLATE as _summarize

    reg = PromptRegistry()
    for tpl in (_goal, _planner, _reason, _summarize, _compare):
        reg.register(tpl)
    return reg


__all__ = ["PromptRegistry", "PromptNotFoundError", "default_registry"]
