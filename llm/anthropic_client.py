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


class AnthropicClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        max_context_tokens: int = 200000,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        provider_name: str = "Anthropic",
        provider_key: str = ProviderType.ANTHROPIC,
    ) -> None:
        super().__init__(
            max_context_tokens=max_context_tokens,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
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
    def _get_value(value: Any, key: str, default: Any = None) -> Any:
        if isinstance(value, Mapping):
            return value.get(key, default)
        return getattr(value, key, default)

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
    def _to_provider_message(message: LLMMessage) -> dict[str, Any]:
        blocks: list[dict[str, Any]] = []
        if message.role != "tool" and message.content:
            blocks.append({"type": "text", "text": message.content})

        if message.role == "assistant" and message.tool_calls:
            for tool_call in message.tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tool_call.id or "",
                        "name": tool_call.name,
                        "input": dict(tool_call.arguments),
                    }
                )
        elif message.role == "tool":
            blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id or "",
                    "content": message.content or "",
                }
            )

        role = "user" if message.role == "tool" else message.role
        return {"role": role, "content": blocks}

    @classmethod
    def _to_provider_messages(
        cls,
        messages: Sequence[LLMMessage],
    ) -> list[dict[str, Any]]:
        provider_messages: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "system":
                continue
            provider_message = cls._to_provider_message(message)
            if (
                provider_messages
                and provider_messages[-1]["role"] == provider_message["role"]
            ):
                provider_messages[-1]["content"].extend(provider_message["content"])
            else:
                provider_messages.append(provider_message)
        return provider_messages

    @staticmethod
    def _to_provider_tools(tools: Sequence[ToolDefinition]) -> list[dict[str, Any]]:
        provider_tools: list[dict[str, Any]] = []
        for tool in tools:
            provider_tools.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": dict(tool.parameters),
                }
            )
        return provider_tools

    @classmethod
    def _extract_response(cls, response: Any) -> LLMResponse:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in cls._get_value(response, "content", ()) or ():
            block_type = cls._get_value(block, "type")
            if block_type == "thinking":
                thinking = cls._get_value(block, "thinking")
                text = cls._get_value(block, "text")
                if thinking:
                    reasoning_parts.append(str(thinking))
                if text:
                    reasoning_parts.append(str(text))
            elif block_type == "redacted_thinking":
                data = cls._get_value(block, "data")
                if data:
                    reasoning_parts.append(str(data))
            elif block_type == "text":
                text = cls._get_value(block, "text")
                if text:
                    content_parts.append(str(text))
            elif block_type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=cls._get_value(block, "id") or "",
                        name=str(cls._get_value(block, "name", "")),
                        arguments=cls._parse_arguments(
                            cls._get_value(block, "input", {}),
                        ),
                    )
                )

        return LLMResponse(
            content="\n".join(content_parts) if content_parts else None,
            reasoning="\n".join(reasoning_parts) if reasoning_parts else None,
            tool_calls=tuple(tool_calls),
            raw=response,
        )

    def _complete_single(self, request: LLMRequest) -> LLMResponse:
        try:
            logging.info(f"LLM request: {request.user_prompt}")

            all_messages = request.all_messages()
            system_parts = [
                message.content
                for message in all_messages
                if message.role == "system" and message.content
            ]

            kwargs: dict[str, Any] = {
                "model": request.model or self._model,
                "max_tokens": 4096,
                "messages": self._to_provider_messages(all_messages),
                "cache_control": {"type": "ephemeral"},
            }
            if system_parts:
                kwargs["system"] = "\n\n".join(system_parts)
            if request.temperature is not None:
                kwargs["temperature"] = request.temperature
            if request.tools:
                kwargs["tools"] = self._to_provider_tools(request.tools)
            if request.tool_choice is not None:
                kwargs["tool_choice"] = request.tool_choice

            response = self._client.messages.create(**kwargs)
            parsed = self._extract_response(response)
            if parsed.content is None and not parsed.tool_calls:
                raise RuntimeError("LLM returned empty response")
            if parsed.reasoning:
                logging.info(f"LLM reasoning: {parsed.reasoning}")
            if parsed.content:
                logging.info(f"LLM response: {parsed.content}")
            if parsed.tool_calls:
                logging.info(
                    f"LLM tool calls: {[tool_call.name for tool_call in parsed.tool_calls]}"
                )
            return parsed
        except RuntimeError:
            raise
        except Exception as e:
            logging.error(f"Anthropic call exception: {type(e).__name__}: {e}")
            raise RuntimeError(f"LLM call failed: {e}") from e
