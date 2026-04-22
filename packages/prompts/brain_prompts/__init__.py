"""Prompt templates and registry for the Brain Agent Platform."""

from brain_prompts.registry import PromptRegistry, default_registry
from brain_prompts.template import PromptTemplate, RenderedPrompt

__all__ = [
    "PromptTemplate",
    "PromptRegistry",
    "RenderedPrompt",
    "default_registry",
]
