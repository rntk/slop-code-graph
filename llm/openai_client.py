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


class OpenAIClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        max_context_tokens: int = 128000,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        provider_name: str = "OpenAI",
        provider_key: str = ProviderType.OPENAI,
    ) -> None:
        super().__init__(
            max_context_tokens=max_context_tokens,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
        import openai

        self._client = openai.OpenAI(api_key=api_key)
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
        provider_tools: list[dict[str, Any]] = []
        for tool in tools:
            provider_tools.append(
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": dict(tool.parameters),
                }
            )
        return provider_tools

    @staticmethod
    def _assistant_items(message: LLMMessage) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if message.content:
            items.append(
                {
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": message.content}],
                }
            )
        for tool_call in message.tool_calls:
            items.append(
                {
                    "type": "function_call",
                    "call_id": tool_call.id or "",
                    "name": tool_call.name,
                    "arguments": json.dumps(dict(tool_call.arguments)),
                }
            )
        return items

    @classmethod
    def _to_input_items(cls, messages: Sequence[LLMMessage]) -> list[dict[str, Any]]:
        input_items: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "system":
                continue
            if message.role == "user":
                input_items.append({"role": "user", "content": message.content or ""})
            elif message.role == "assistant":
                input_items.extend(cls._assistant_items(message))
            elif message.role == "tool":
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.tool_call_id or "",
                        "output": message.content or "",
                    }
                )
        return input_items

    @staticmethod
    def _extract_reasoning(response: Any) -> str | None:
        reasoning_parts: list[str] = []
        for item in getattr(response, "output", []) or []:
            item_type = getattr(item, "type", None)
            if item_type == "reasoning":
                for summary in getattr(item, "summary", []) or []:
                    text = getattr(summary, "text", None)
                    if text:
                        reasoning_parts.append(str(text))
            elif item_type == "message":
                for content_item in getattr(item, "content", []) or []:
                    if getattr(content_item, "type", None) == "reasoning":
                        for summary in getattr(content_item, "summary", []) or []:
                            text = getattr(summary, "text", None)
                            if text:
                                reasoning_parts.append(str(text))
        combined = "\n".join(part for part in reasoning_parts if part)
        return combined or None

    @classmethod
    def _extract_response(cls, response: Any) -> LLMResponse:
        content_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for item in getattr(response, "output", []) or []:
            item_type = getattr(item, "type", None)
            if item_type == "message":
                for content_item in getattr(item, "content", []) or []:
                    if getattr(content_item, "type", None) == "output_text":
                        text = getattr(content_item, "text", None)
                        if text:
                            content_parts.append(str(text))
            elif item_type == "function_call":
                tool_calls.append(
                    ToolCall(
                        id=getattr(item, "call_id", None),
                        name=str(getattr(item, "name", "")),
                        arguments=cls._parse_arguments(
                            getattr(item, "arguments", None),
                        ),
                    )
                )

        return LLMResponse(
            content="\n".join(content_parts) if content_parts else None,
            reasoning=cls._extract_reasoning(response),
            tool_calls=tuple(tool_calls),
            raw=response,
        )

    def _complete_single(self, request: LLMRequest) -> LLMResponse:
        try:
            logging.info(f"LLM request: {request.user_prompt}")

            all_messages = request.all_messages()
            instructions_parts = [
                message.content
                for message in all_messages
                if message.role == "system" and message.content
            ]

            kwargs: dict[str, Any] = {
                "model": request.model or self._model,
                "input": self._to_input_items(all_messages),
            }
            if instructions_parts:
                kwargs["instructions"] = "\n\n".join(instructions_parts)
            if request.tools:
                kwargs["tools"] = self._to_provider_tools(request.tools)
            if request.tool_choice is not None:
                kwargs["tool_choice"] = request.tool_choice
            if request.parallel_tool_calls is not None:
                kwargs["parallel_tool_calls"] = request.parallel_tool_calls
            if request.temperature is not None and kwargs["model"] not in (
                "gpt-5-mini",
                "gpt-5-nano",
            ):
                kwargs["temperature"] = request.temperature
            kwargs["service_tier"] = "flex"

            response = self._client.responses.create(**kwargs)
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
            logging.error(f"OpenAI call exception: {type(e).__name__}: {e}")
            raise RuntimeError(f"LLM call failed: {e}") from e
