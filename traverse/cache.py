"""On-disk cache for LLM flow summaries."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any


class SummaryCache:
    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = cache_dir
        self._lock = threading.Lock()
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _key_path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{digest}.json"

    def make_key(
        self,
        *,
        scope_file: str,
        start_stable_key: str,
        reachable_signature: str,
        mtimes_signature: str,
    ) -> str:
        return "|".join([scope_file, start_stable_key, reachable_signature, mtimes_signature])

    @staticmethod
    def reachable_signature(node_ids: list[str]) -> str:
        joined = ",".join(sorted(node_ids))
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def mtimes_signature(file_mtimes: dict[str, float]) -> str:
        parts = [f"{path}:{mtime}" for path, mtime in sorted(file_mtimes.items())]
        joined = "|".join(parts)
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._key_path(key)
        if not path.exists():
            return None
        with self._lock:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        path = self._key_path(key)
        with self._lock:
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
