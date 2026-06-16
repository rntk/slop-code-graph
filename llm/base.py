import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional

from llm.constants import ProviderType


@dataclass(frozen=True)
class ProviderDefinition:
    key: str
    display_name: str
    models: tuple[str, ...]
    default_model: str


MessageRole = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: Mapping[str, Any]
    id: str | None = None


@dataclass(frozen=True)
class LLMMessage:
    role: MessageRole
    content: str | None = None
    tool_calls: Sequence[ToolCall] = field(default_factory=tuple)
    tool_call_id: str | None = None
    reasoning: str | None = None


@dataclass(frozen=True)
class LLMRequest:
    user_prompt: str
    system_prompt: str | None = None
    tools: Sequence[ToolDefinition] = field(default_factory=tuple)
    model: str | None = None
    temperature: float | None = None
    messages: Sequence[LLMMessage] = field(default_factory=tuple)
    tool_choice: str | dict[str, Any] | None = None
    parallel_tool_calls: bool | None = None

    def all_messages(self) -> tuple[LLMMessage, ...]:
        messages: list[LLMMessage] = []
        if self.system_prompt:
            messages.append(LLMMessage(role="system", content=self.system_prompt))
        messages.extend(self.messages)
        if self.user_prompt:
            messages.append(LLMMessage(role="user", content=self.user_prompt))
        return tuple(messages)


@dataclass(frozen=True)
class LLMResponse:
    content: str | None = None
    reasoning: str | None = None
    tool_calls: Sequence[ToolCall] = field(default_factory=tuple)
    raw: Any | None = None


DEFAULT_PROVIDER_DEFINITIONS: tuple[ProviderDefinition, ...] = (
    ProviderDefinition(
        key=ProviderType.LLAMACPP,
        display_name="LlamaCPP",
        models=("moonshotai/Kimi-K2.5",),
        default_model="moonshotai/Kimi-K2.5",
    ),
    ProviderDefinition(
        key=ProviderType.OPENAI,
        display_name="OpenAI",
        models=(
            "",
            "gpt-5-mini",
            "gpt-5-nano",
            "gpt-5.4-mini",
            "gpt-5.4-nano",
            "gpt-5.4",
        ),
        default_model="gpt-5.4-nano",
    ),
    ProviderDefinition(
        key=ProviderType.ANTHROPIC,
        display_name="Anthropic",
        models=("claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-6"),
        default_model="claude-haiku-4-5",
    ),
    ProviderDefinition(
        key=ProviderType.OPENROUTER,
        display_name="OpenRouter",
        models=(
            "",
            "openai/gpt-4o-mini",
            "openai/gpt-4o",
            "anthropic/claude-3.5-haiku",
            "anthropic/claude-sonnet-4-5",
            "google/gemini-2.0-flash-001",
            "meta-llama/llama-3.3-70b-instruct",
        ),
        default_model="openai/gpt-4o-mini",
    ),
)

# Compile-time defaults; used as seed source and as a fallback when no DB is
# available. Runtime lookups should go through load_provider_definitions(db).
PROVIDER_DEFINITION_BY_KEY: dict[str, ProviderDefinition] = {
    provider.key: provider for provider in DEFAULT_PROVIDER_DEFINITIONS
}
PROVIDER_DEFINITION_BY_NAME: dict[str, ProviderDefinition] = {
    provider.display_name: provider for provider in DEFAULT_PROVIDER_DEFINITIONS
}


def load_provider_definitions(db: Any = None) -> tuple[ProviderDefinition, ...]:
    """Return provider definitions from the DB, falling back to hardcoded defaults."""
    if db is None:
        return DEFAULT_PROVIDER_DEFINITIONS
    try:
        from lib.storage.llm_builtin_providers import LlmBuiltinProvidersStorage

        stored = LlmBuiltinProvidersStorage(db).list_definitions()
    except Exception:
        logging.getLogger(__name__).debug(
            "Failed to load built-in LLM provider definitions from DB", exc_info=True
        )
        return DEFAULT_PROVIDER_DEFINITIONS
    if not stored:
        return DEFAULT_PROVIDER_DEFINITIONS
    # Preserve DEFAULT_PROVIDER_DEFINITIONS order; append any DB-only keys at the end.
    by_key = {definition.key: definition for definition in stored}
    ordered: list[ProviderDefinition] = []
    seen: set[str] = set()
    for default in DEFAULT_PROVIDER_DEFINITIONS:
        if default.key in by_key:
            ordered.append(by_key[default.key])
            seen.add(default.key)
    for definition in stored:
        if definition.key not in seen:
            ordered.append(definition)
    return tuple(ordered)


def get_provider_definition_by_key(
    provider_key: str, db: Any = None
) -> ProviderDefinition:
    for definition in load_provider_definitions(db):
        if definition.key == provider_key:
            return definition
    raise KeyError(f"Unknown LLM provider key: {provider_key}")


def get_provider_definition_by_name(
    provider_name: str, db: Any = None
) -> ProviderDefinition:
    for definition in load_provider_definitions(db):
        if definition.display_name == provider_name:
            return definition
    raise KeyError(f"Unknown LLM provider name: {provider_name}")


class LLMClient(ABC):
    def __init__(
        self, max_context_tokens: int, max_retries: int = 3, retry_delay: float = 1.0
    ):
        self._max_context_tokens = max_context_tokens
        self._max_retries = max_retries
        self._retry_delay = retry_delay

    @property
    def max_context_tokens(self) -> int:
        return self._max_context_tokens

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @property
    @abstractmethod
    def provider_key(self) -> str:
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        pass

    @property
    def model_id(self) -> str:
        return f"{self.provider_key}:{self.model_name}"

    def estimate_tokens(self, text: str) -> int:
        """Rough estimation: ~4 characters per token on average"""
        return len(text) // 4

    def call(
        self,
        user_msgs: List[str],
        temperature: float = 0.0,
        retries: Optional[int] = None,
    ) -> str:
        """Call the LLM with retry logic and exponential backoff."""
        if not user_msgs:
            raise RuntimeError("LLM call requires at least one user message")

        response = self.complete(
            user_prompt=user_msgs[0],
            temperature=temperature,
            retries=retries,
        )
        if response.content is None:
            raise RuntimeError("LLM returned empty text response")
        return response.content

    def complete(
        self,
        user_prompt: str,
        *,
        system_prompt: str | None = None,
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
        temperature: float | None = None,
        messages: Sequence[LLMMessage] = (),
        tool_choice: str | dict[str, Any] | None = None,
        parallel_tool_calls: bool | None = None,
        retries: Optional[int] = None,
    ) -> LLMResponse:
        request = LLMRequest(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            tools=tools,
            model=model,
            temperature=temperature,
            messages=messages,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
        )
        max_retries = retries if retries is not None else self._max_retries

        for attempt in range(max_retries + 1):
            try:
                return self._complete_single(request)
            except RuntimeError as e:
                if attempt < max_retries:
                    delay = self._retry_delay * (2**attempt) + random.uniform(0, 0.5)
                    logging.warning(
                        f"LLM call failed (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                        f"Retrying in {delay:.2f}s..."
                    )
                    time.sleep(delay)
                else:
                    logging.error(
                        f"LLM call failed after {max_retries + 1} attempts: {e}"
                    )
                    raise

    @abstractmethod
    def _complete_single(self, request: LLMRequest) -> LLMResponse:
        pass
