"""Provider implementations. Import lazily — keep optional deps optional."""

from brain_llm.providers.mock import MockLLMProvider, Responder

__all__ = ["MockLLMProvider", "Responder", "AnthropicProvider"]


def __getattr__(name: str):
    # Lazy so importing brain_llm.providers doesn't require the anthropic SDK.
    if name == "AnthropicProvider":
        from brain_llm.providers.anthropic import AnthropicProvider

        return AnthropicProvider
    raise AttributeError(f"module 'brain_llm.providers' has no attribute {name!r}")
