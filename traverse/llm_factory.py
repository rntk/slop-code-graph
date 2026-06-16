"""Create LLM clients for Traverse (llamacpp-first)."""

from __future__ import annotations

import os

from llm.base import LLMClient
from llm.constants import ProviderType
from llm.llamacpp import LLamaCPP
from traverse.config import TraverseConfig


def create_llm_client(config: TraverseConfig) -> LLMClient:
    provider = config.llm_provider
    if provider in (ProviderType.LLAMACPP, "llamacpp", "local"):
        url = os.getenv("LLAMACPP_URL")
        if not url:
            raise RuntimeError(
                "No LLM configured. Set LLAMACPP_URL for local LlamaCPP, "
                "or TRAVERSE_LLM_PROVIDER with the appropriate API key."
            )
        model = config.llm_model or os.getenv("LLAMACPP_MODEL", "moonshotai/Kimi-K2.5")
        return LLamaCPP(
            host=url,
            token=os.getenv("TOKEN"),
            model=model,
            max_retries=3,
            retry_delay=1.0,
            temperature=0.1,
        )
    raise RuntimeError(
        f"Unsupported TRAVERSE_LLM_PROVIDER={provider!r}. Initial version supports only llamacpp."
    )


def llm_available(config: TraverseConfig) -> bool:
    try:
        create_llm_client(config)
        return True
    except RuntimeError:
        return False
