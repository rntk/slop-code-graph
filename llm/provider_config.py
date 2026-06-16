"""File-backed LLM provider configuration for remote workers."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm.base import LLMClient
from llm.constants import ProviderType

VALID_CONFIG_TYPES = (
    ProviderType.OPENAI,
    ProviderType.ANTHROPIC,
    ProviderType.OPENAI_COMP,
    ProviderType.OPENROUTER,
)


@dataclass(frozen=True)
class RemoteProviderConfigEntry:
    id: str
    name: str
    type: str
    model: str
    token: str
    url: str | None = None

    @property
    def model_id(self) -> str:
        return f"{self.id}:{self.model}"


class RemoteProviderConfig:
    def __init__(self, providers: list[RemoteProviderConfigEntry]) -> None:
        if not providers:
            raise ValueError("Remote worker provider config must contain providers")
        model_ids = [provider.model_id for provider in providers]
        if len(set(model_ids)) != len(model_ids):
            raise ValueError("Remote worker provider config has duplicate model IDs")
        self._providers_by_model_id: dict[str, RemoteProviderConfigEntry] = {
            provider.model_id: provider for provider in providers
        }

    @property
    def supported_model_ids(self) -> list[str]:
        return list(self._providers_by_model_id.keys())

    def create_client(self, provider_id: str, model: str) -> LLMClient:
        model_id = f"{provider_id}:{model}"
        provider = self._providers_by_model_id.get(model_id)
        if provider is None:
            raise RuntimeError(
                f"Remote worker provider config does not support {model_id!r}"
            )

        if provider.type == ProviderType.OPENAI_COMP:
            from llm.llamacpp import (
                CerebrasLLamaCPP,
                LLamaCPP,
                is_cerebras_provider,
            )

            if not provider.url:
                raise RuntimeError(
                    f"Remote provider {provider.id!r} requires url for openai_comp"
                )
            llm_client_type: type[LLamaCPP] = (
                CerebrasLLamaCPP
                if is_cerebras_provider(provider_name=provider.name, url=provider.url)
                else LLamaCPP
            )
            return llm_client_type(
                host=provider.url,
                token=provider.token,
                model=provider.model,
                provider_name=provider.name,
                provider_key=provider.id,
                max_retries=5,
                retry_delay=2.0,
            )

        if provider.type == ProviderType.OPENAI:
            from llm.openai_client import OpenAIClient

            return OpenAIClient(
                api_key=provider.token,
                model=provider.model,
                provider_name=provider.name,
                provider_key=provider.id,
            )

        if provider.type == ProviderType.ANTHROPIC:
            from llm.anthropic_client import AnthropicClient

            return AnthropicClient(
                api_key=provider.token,
                model=provider.model,
                provider_name=provider.name,
                provider_key=provider.id,
            )

        if provider.type == ProviderType.OPENROUTER:
            from llm.openrouter_client import OpenRouterClient

            return OpenRouterClient(
                api_key=provider.token,
                model=provider.model,
                provider_name=provider.name,
                provider_key=provider.id,
            )

        raise RuntimeError(f"Unsupported remote provider type: {provider.type}")


def _require_string(data: dict[str, Any], key: str, index: int) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"providers[{index}].{key} must be a non-empty string")
    return value.strip()


def _parse_provider(data: Any, index: int) -> RemoteProviderConfigEntry:
    if not isinstance(data, dict):
        raise ValueError(f"providers[{index}] must be an object")

    provider_type = _require_string(data, "type", index)
    if provider_type not in VALID_CONFIG_TYPES:
        raise ValueError(
            f"providers[{index}].type must be one of: {', '.join(VALID_CONFIG_TYPES)}"
        )

    url_value = data.get("url")
    url = (
        url_value.strip() if isinstance(url_value, str) and url_value.strip() else None
    )
    if provider_type == ProviderType.OPENAI_COMP and url is None:
        raise ValueError(
            f"providers[{index}].url is required for {ProviderType.OPENAI_COMP}"
        )

    return RemoteProviderConfigEntry(
        id=_require_string(data, "id", index),
        name=_require_string(data, "name", index),
        type=provider_type,
        model=_require_string(data, "model", index),
        token=_require_string(data, "token", index),
        url=url,
    )


def load_remote_provider_config(path: str | Path) -> RemoteProviderConfig:
    config_path = Path(path)
    with config_path.open(encoding="utf-8") as file_obj:
        data: Any = json.load(file_obj)

    if not isinstance(data, dict):
        raise ValueError("Remote worker provider config must be a JSON object")

    providers_data = data.get("providers")
    if not isinstance(providers_data, list):
        raise ValueError("Remote worker provider config requires a providers list")

    providers = [
        _parse_provider(provider_data, index)
        for index, provider_data in enumerate(providers_data)
    ]
    return RemoteProviderConfig(providers)
