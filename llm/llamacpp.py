import json
import logging
import os
import re
from collections.abc import Mapping, Sequence
from http.client import HTTPConnection, HTTPSConnection
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from llm.base import (
    LLMClient,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    ToolCall,
    ToolDefinition,
)
from llm.constants import ProviderType

_THINK_TAG_RE = re.compile(
    r"<think\b[^>]*>(.*?)</think>",
    flags=re.DOTALL | re.IGNORECASE,
)


def is_cerebras_provider(provider_name: str, url: str | None) -> bool:
    values: tuple[str, ...] = tuple(
        value.lower() for value in (provider_name, url or "") if value
    )
    return any("cerebras" in value for value in values)


class LLamaCPP(LLMClient):
    def __init__(
        self,
        host: str,
        model: str = "moonshotai/Kimi-K2.5",
        max_context_tokens: int = 11000,
        token: Optional[str] = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        temperature: float = 0.8,
        min_p: float = 0.05,
        repeat_penalty: float = 1.1,
        repeat_last_n: int = 64,
        dry_multiplier: float = 0.8,
        dry_base: float = 1.75,
        dry_allowed_length: int = 2,
        stop: Optional[List[str]] = None,
        provider_name: str = "LlamaCPP",
        provider_key: str = ProviderType.LLAMACPP,
    ) -> None:
        super().__init__(
            max_context_tokens=max_context_tokens,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
        u = urlparse(host)
        self.__host = u.netloc
        self.__is_https = u.scheme.lower() == "https"
        self.__model = model
        # Token can be passed in explicitly or read from the environment variable TOKEN
        self.__token = token or os.getenv("TOKEN")
        self.__temperature = temperature
        self.__min_p = min_p
        self.__repeat_penalty = repeat_penalty
        self.__repeat_last_n = repeat_last_n
        self.__dry_multiplier = dry_multiplier
        self.__dry_base = dry_base
        self.__dry_allowed_length = dry_allowed_length
        self.__stop = stop or ["User:", "\n\n"]
        self.__provider_name = provider_name
        self.__provider_key = provider_key

    @property
    def provider_name(self) -> str:
        return self.__provider_name

    @property
    def provider_key(self) -> str:
        return self.__provider_key

    @property
    def model_name(self) -> str:
        return self.__model

    def _extract_reasoning_and_content(
        self,
        response_payload: dict[str, Any],
    ) -> tuple[str | None, str | None]:
        choices = response_payload.get("choices")
        first_choice = choices[0] if isinstance(choices, list) and choices else {}
        message = first_choice.get("message") if isinstance(first_choice, dict) else {}
        if not isinstance(message, dict):
            message = {}

        raw_content = message.get("content")
        content = raw_content if isinstance(raw_content, str) else ""

        reasoning_parts: list[str] = []
        for key in ("reasoning", "reasoning_content", "thinking"):
            value = message.get(key)
            if isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    reasoning_parts.append(stripped)

        for think_match in _THINK_TAG_RE.findall(content):
            stripped = think_match.strip()
            if stripped:
                reasoning_parts.append(stripped)

        reasoning = "\n\n".join(reasoning_parts).strip() or None
        cleaned_content = _THINK_TAG_RE.sub("", content).strip() or None
        return reasoning, cleaned_content

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
        output: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.role == "tool":
            output["tool_call_id"] = message.tool_call_id
        if message.reasoning:
            output["reasoning_content"] = message.reasoning
        if message.tool_calls:
            output["tool_calls"] = [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": json.dumps(dict(tool_call.arguments)),
                    },
                }
                for tool_call in message.tool_calls
            ]
        return output

    @staticmethod
    def _combined_system_prompt(messages: Sequence[LLMMessage]) -> str | None:
        system_parts: list[str] = [
            message.content
            for message in messages
            if message.role == "system" and message.content
        ]
        return "\n\n".join(system_parts) if system_parts else None

    @classmethod
    def _to_provider_messages(
        cls,
        messages: Sequence[LLMMessage],
    ) -> list[dict[str, Any]]:
        provider_messages: list[dict[str, Any]] = []
        system_prompt = cls._combined_system_prompt(messages)
        if system_prompt:
            provider_messages.append({"role": "system", "content": system_prompt})

        provider_messages.extend(
            cls._to_provider_message(message)
            for message in messages
            if message.role != "system"
        )
        return provider_messages

    @staticmethod
    def _request_messages(request: LLMRequest) -> tuple[LLMMessage, ...]:
        messages = request.all_messages()
        if request.user_prompt == "" and not any(
            message.role == "user" for message in messages
        ):
            messages = (*messages, LLMMessage(role="user", content=""))
        return messages

    def _prepare_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return payload

    @classmethod
    def _from_provider_tool_calls(cls, tool_calls: Any) -> tuple[ToolCall, ...]:
        if not tool_calls:
            return ()

        parsed_calls: list[ToolCall] = []
        for tool_call in tool_calls:
            function = tool_call.get("function", tool_call)
            parsed_calls.append(
                ToolCall(
                    id=tool_call.get("id", tool_call.get("call_id")),
                    name=str(function.get("name", "")),
                    arguments=cls._parse_arguments(function.get("arguments", "{}")),
                )
            )
        return tuple(parsed_calls)

    def _complete_single(self, request: LLMRequest) -> LLMResponse:
        """Single attempt to call the LLM without retry logic."""
        conn = self.get_connection()
        try:
            request_messages = self._to_provider_messages(
                self._request_messages(request)
            )
            logging.info(
                "LLM request: %d messages (system=%s)",
                len(request_messages),
                any(m.get("role") == "system" for m in request_messages),
            )

            payload: dict[str, Any] = {
                "model": request.model or self.__model,
                "messages": request_messages,
                "temperature": (
                    request.temperature
                    if request.temperature is not None
                    else self.__temperature
                ),
                "cache_prompt": True,
                # "min_p": self.__min_p,
                # "repeat_penalty": self.__repeat_penalty,
                # "repeat_last_n": self.__repeat_last_n,
                # "dry_multiplier": self.__dry_multiplier,
                # "dry_base": self.__dry_base,
                # "dry_allowed_length": self.__dry_allowed_length,
                # "stop": self.__stop,
            }
            if request.tools:
                payload["tools"] = self._to_provider_tools(request.tools)
            if request.tool_choice is not None:
                payload["tool_choice"] = request.tool_choice
            if request.parallel_tool_calls is not None:
                payload["parallel_tool_calls"] = request.parallel_tool_calls

            payload = self._prepare_payload(payload)
            body = json.dumps(payload)
            headers = {"Content-type": "application/json"}
            if self.__token:
                headers["Authorization"] = f"Bearer {self.__token}"
            conn.request("POST", "/v1/chat/completions", body, headers)
            res = conn.getresponse()
            resp_body = res.read()
            if res.status != 200:
                err_msg = f"{res.status} - {res.reason} - {resp_body}"
                logging.error(err_msg)
                raise RuntimeError(f"LLM API error: {res.status} {res.reason}")

            resp = json.loads(resp_body)

            reasoning, content = self._extract_reasoning_and_content(resp)
            choices = resp.get("choices")
            first_choice = choices[0] if isinstance(choices, list) and choices else {}
            message = (
                first_choice.get("message") if isinstance(first_choice, dict) else {}
            )
            if not isinstance(message, dict):
                message = {}
            tool_calls = self._from_provider_tool_calls(message.get("tool_calls"))

            if content is None and not tool_calls:
                logging.error("LLM response missing text content and tool calls")
                logging.error(f"Full response: {resp}")
                raise RuntimeError("LLM returned empty response")
            if reasoning:
                logging.info(f"LLM reasoning: {reasoning}")
            if content:
                logging.info(f"LLM response: {content}")
            if tool_calls:
                logging.info(
                    f"LLM tool calls: {[tool_call.name for tool_call in tool_calls]}"
                )
            return LLMResponse(
                content=content,
                reasoning=reasoning,
                tool_calls=tool_calls,
                raw=resp,
            )
        except json.JSONDecodeError as e:
            err_msg = f"JSON decode error: {e}"
            logging.error(err_msg)
            raise RuntimeError(f"Invalid JSON response from LLM: {e}") from e
        except RuntimeError:
            raise
        except Exception as e:
            err_msg = f"LLM call exception: {type(e).__name__}: {e}"
            logging.error(err_msg)
            raise RuntimeError(f"LLM call failed: {e}") from e
        finally:
            conn.close()

    def get_connection(self) -> Union[HTTPConnection, HTTPSConnection]:
        if self.__is_https:
            return HTTPSConnection(self.__host)
        else:
            return HTTPConnection(self.__host)

    def embeddings(self, texts: List[str]) -> Optional[List[List[float]]]:
        conn = self.get_connection()
        try:
            body = json.dumps(
                {
                    "model": "text-embedding-3-small",
                    "encoding_format": "float",
                    "input": texts,
                }
            )
            headers = {"Content-type": "application/json"}
            if self.__token:
                headers["Authorization"] = f"Bearer {self.__token}"
            conn.request("POST", "/v1/embeddings", body, headers)
            res = conn.getresponse()
            resp_body = res.read()
            if res.status != 200:
                err_msg = f"{res.status} - {res.reason} - {resp_body}"
                logging.error(err_msg)
                return None
            resp = json.loads(resp_body)
            embeds = []
            for emb in resp["data"]:
                embeds.append(emb["embedding"])

            return embeds
        except Exception as e:
            err_msg = f"Embeddings exception: {type(e).__name__}: {e}"
            logging.error(err_msg)
            return None
        finally:
            conn.close()

    def rerank(
        self, query: str, documents: List[str], top_n: Optional[int] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Reranks documents according to their relevance to the query.

        Args:
            query: The query string to rank documents against
            documents: List of document strings to rank
            top_n: Optional number of top documents to return (default returns all documents)

        Returns:
            List of dictionaries containing:
                - document: The original document text
                - index: Original index of the document in the input list
                - relevance_score: A float indicating relevance (higher is more relevant)
            Sorted by relevance_score in descending order, or None if the API call fails.
        """
        conn = self.get_connection()
        try:
            request_body = {"query": query, "documents": documents}

            if top_n is not None:
                request_body["top_n"] = top_n

            body = json.dumps(request_body)
            headers = {"Content-type": "application/json"}
            if self.__token:
                headers["Authorization"] = f"Bearer {self.__token}"

            conn.request("POST", "/v1/rerank", body, headers)
            res = conn.getresponse()
            resp_body = res.read()

            if res.status != 200:
                err_msg = f"{res.status} - {res.reason} - {resp_body}"
                logging.error(err_msg)

                return None

            resp = json.loads(resp_body)

            return resp.get("results", [])
        except Exception as e:
            err_msg = f"Rerank exception: {type(e).__name__}: {e}"
            logging.error(err_msg)
            return None
        finally:
            conn.close()


class CerebrasLLamaCPP(LLamaCPP):
    """OpenAI-compatible client variant for Cerebras unsupported request fields."""

    @staticmethod
    def _to_provider_message(message: LLMMessage) -> dict[str, Any]:
        output: dict[str, Any] = LLamaCPP._to_provider_message(message)
        output.pop("reasoning_content", None)
        return output

    def _prepare_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        prepared_payload: dict[str, Any] = dict(payload)
        prepared_payload.pop("cache_prompt", None)
        return prepared_payload
