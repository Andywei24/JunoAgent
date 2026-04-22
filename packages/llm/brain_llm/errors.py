"""Typed errors surfaced by the LLM layer."""

from __future__ import annotations


class LLMError(RuntimeError):
    """Base class — everything the LLM layer raises inherits from this."""


class ProviderUnavailableError(LLMError):
    """Provider SDK/credentials missing, or the remote is refusing requests."""


class MalformedOutputError(LLMError):
    """Model responded but the structured output could not be parsed/validated."""
