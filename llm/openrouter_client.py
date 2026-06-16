import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from llm.base import (
    LLMClient,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    ToolCall,
    ToolDefinition,
)
from llm.constants import ProviderType

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        model: str = "openai/gpt-4o-mini",
        max_context_tokens: int = 128000,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        provider_name: str = "OpenRouter",
        provider_key: str = ProviderType.OPENROUTER,
    ) -> None:
        super().__init__(
            max_context_tokens=max_context_tokens,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
        import openai

        self._client = openai.OpenAI(
            api_key=api_key,
            base_url=OPENROUTER_BASE_URL,
        )
        self._model = model
        self._provider_name = provider_name
        self._provider_key = provider_key

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def provider_key(self) -> str:
        return self._provider_key

    @property
    def model_name(self) -> str:
        return self._model

    @staticmethod
    def _parse_arguments(arguments: Any) -> Mapping[str, Any]:
        if arguments is None:
            return {}
        if isinstance(arguments, str):
            decoded = json.loads(arguments or "{}")
            if not isinstance(decoded, dict):
                raise ValueError("Tool-call arguments must decode to a JSON object.")
            return decoded
        if isinstance(arguments, Mapping):
            return arguments
        raise ValueError("Tool-call arguments must be a JSON object string or mapping.")

    @staticmethod
    def _to_provider_tools(tools: Sequence[ToolDefinition]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": dict(tool.parameters),
                },
            }
            for tool in tools
        ]

    @staticmethod
    def _to_provider_message(message: LLMMessage) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.role == "tool":
            msg["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id or "",
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(dict(tc.arguments)),
                    },
                }
                for tc in message.tool_calls
            ]
        return msg

    @classmethod
    def _to_provider_messages(
        cls, messages: Sequence[LLMMessage]
    ) -> list[dict[str, Any]]:
        system_parts = [m.content for m in messages if m.role == "system" and m.content]
        provider_messages: list[dict[str, Any]] = []
        if system_parts:
            provider_messages.append(
                {"role": "system", "content": "\n\n".join(system_parts)}
            )
        provider_messages.extend(
            cls._to_provider_message(m) for m in messages if m.role != "system"
        )
        return provider_messages

    @classmethod
    def _extract_response(cls, response: Any) -> LLMResponse:
        choice = response.choices[0] if response.choices else None
        if choice is None:
            return LLMResponse(raw=response)

        message = choice.message
        content: str | None = message.content or None

        tool_calls: list[ToolCall] = []
        for tc in getattr(message, "tool_calls", None) or []:
            tool_calls.append(
                ToolCall(
                    id=getattr(tc, "id", None),
                    name=tc.function.name,
                    arguments=cls._parse_arguments(tc.function.arguments),
                )
            )

        return LLMResponse(
            content=content,
            tool_calls=tuple(tool_calls),
            raw=response,
        )

    def _complete_single(self, request: LLMRequest) -> LLMResponse:
        try:
            logging.info(f"OpenRouter request: {request.user_prompt}")

            kwargs: dict[str, Any] = {
                "model": request.model or self._model,
                "messages": self._to_provider_messages(request.all_messages()),
            }
            if request.tools:
                kwargs["tools"] = self._to_provider_tools(request.tools)
            if request.tool_choice is not None:
                kwargs["tool_choice"] = request.tool_choice
            if request.parallel_tool_calls is not None:
                kwargs["parallel_tool_calls"] = request.parallel_tool_calls
            if request.temperature is not None:
                kwargs["temperature"] = request.temperature

            response = self._client.chat.completions.create(**kwargs)
            parsed = self._extract_response(response)
            if parsed.content is None and not parsed.tool_calls:
                raise RuntimeError("LLM returned empty response")
            if parsed.content:
                logging.info(f"OpenRouter response: {parsed.content}")
            if parsed.tool_calls:
                logging.info(
                    f"OpenRouter tool calls: {[tc.name for tc in parsed.tool_calls]}"
                )
            return parsed
        except RuntimeError:
            raise
        except Exception as e:
            logging.error(f"OpenRouter call exception: {type(e).__name__}: {e}")
            raise RuntimeError(f"LLM call failed: {e}") from e
