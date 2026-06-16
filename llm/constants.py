"""LLM provider type constants."""

from enum import Enum


class ProviderType(str, Enum):
    """Canonical provider type strings used across the backend."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENROUTER = "openrouter"
    OPENAI_COMP = "openai_comp"
    LLAMACPP = "llamacpp"
