"""Environment-driven configuration for the Traverse server."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TraverseConfig:
    host: str
    port: int
    project_root: Path
    llm_provider: str
    llm_model: str | None
    cache_dir: Path
    prompt_char_budget: int

    @property
    def llm_label(self) -> str:
        model = self.llm_model or "default"
        return f"{self.llm_provider}:{model}"


def load_config(project_root: Path | None = None) -> TraverseConfig:
    root = (project_root or Path.cwd()).resolve()
    cache = os.getenv("TRAVERSE_CACHE_DIR")
    return TraverseConfig(
        host=os.getenv("TRAVERSE_HOST", "127.0.0.1"),
        port=int(os.getenv("TRAVERSE_PORT", "8765")),
        project_root=root,
        llm_provider=os.getenv("TRAVERSE_LLM_PROVIDER", "llamacpp").lower(),
        llm_model=os.getenv("TRAVERSE_LLM_MODEL") or None,
        cache_dir=Path(cache) if cache else root / ".traverse-cache",
        prompt_char_budget=int(os.getenv("TRAVERSE_PROMPT_CHAR_BUDGET", "48000")),
    )
