"""Canvas pipeline: glue flow code → LLM topic-range split → per-topic summaries.

Mirrors ext/worker/orchestrator.js (tag-then-chunk with GLOBAL markers, parse
against the total unit count, then summarize each topic) but runs in Python
against the deterministic call graph, using the existing LLM client. Produces
the ``canvas`` dict embedded in the HTML (see ``src/canvas/CONTRACT.md``).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.graph_builder import CallGraph

from .flow_document import build_flow_document
from .prompts import (
    build_code_section_summary_prompt,
    build_tagged_text,
    build_topic_ranges_prompt,
    chunk_tagged_text,
    parse_summary_response,
)
from .topic_parser import TopicParseError, parse_topic_ranges

# Char budget per LLM topic-ranges request. Markers are global, so chunking is
# purely a context-window concern (mirrors MAX_TAGGED_CHARS in orchestrator.js).
MAX_TAGGED_CHARS = 24000
TOPIC_RANGE_TEMPERATURE = 0.2
TOPIC_RANGE_MAX_ATTEMPTS = 3
SUMMARY_TEMPERATURE = 0.8


class _Cache:
    """Tiny sha256(prompt)->text JSON cache, same pattern as graph file summaries."""

    def __init__(self, cache_dir: Path | None):
        self.path: Path | None = None
        self.data: dict[str, str] = {}
        if cache_dir:
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                self.path = cache_dir / "canvas_llm_cache.json"
                if self.path.exists():
                    with open(self.path, encoding="utf-8") as f:
                        self.data = json.load(f)
            except Exception as e:  # noqa: BLE001
                print(f"  Warning: failed to load canvas LLM cache: {e}")

    @staticmethod
    def key(*parts: str) -> str:
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def put(self, key: str, value: str) -> None:
        if self.path is None:
            return
        self.data[key] = value
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            print(f"  Warning: failed to write canvas LLM cache: {e}")


def _ranges_to_line_numbers(ranges: list[dict]) -> list[int]:
    """0-based inclusive ranges -> sorted unique 1-based unit numbers."""
    nums: set[int] = set()
    for r in ranges:
        for i in range(r["start"], r["end"] + 1):
            nums.add(i + 1)
    return sorted(nums)


def _query_topic_groups(
    lines: list[str], llm, cache: _Cache
) -> list[dict]:
    """Tag globally, chunk, query each chunk, parse against the total line count."""
    tagged = build_tagged_text(lines)
    chunks = (
        chunk_tagged_text(tagged, MAX_TAGGED_CHARS)
        if len(tagged) > MAX_TAGGED_CHARS
        else [tagged]
    )

    last_err: Exception | None = None
    for attempt in range(TOPIC_RANGE_MAX_ATTEMPTS):
        responses: list[str] = []
        for chunk in chunks:
            prompt = build_topic_ranges_prompt(chunk)
            # Cache keyed by the exact prompt; identical chunks reuse the answer.
            ckey = cache.key("topic_ranges", prompt)
            cached = cache.get(ckey)
            if cached is not None and attempt == 0:
                responses.append(cached)
                continue
            resp = llm.complete(
                user_prompt=prompt, temperature=TOPIC_RANGE_TEMPERATURE
            )
            text = (resp.content or "").strip()
            responses.append(text)
            if text:
                cache.put(ckey, text)

        combined = "\n".join(responses)
        try:
            return parse_topic_ranges(combined, len(lines))
        except TopicParseError as e:
            last_err = e
            continue

    raise RuntimeError(
        f"LLM topic-range split failed after {TOPIC_RANGE_MAX_ATTEMPTS} attempts: {last_err}"
    )


def _summarize_topic(
    topic_path: str, ranges: list[dict], lines: list[str], llm, cache: _Cache
) -> str:
    code = "\n".join(
        lines[i] for r in ranges for i in range(r["start"], r["end"] + 1)
    ).strip()
    if not code:
        return ""
    prompt = build_code_section_summary_prompt(topic_path, code)
    ckey = cache.key("summary", prompt)
    cached = cache.get(ckey)
    if cached is not None:
        return cached
    try:
        resp = llm.complete(user_prompt=prompt, temperature=SUMMARY_TEMPERATURE)
    except Exception:  # noqa: BLE001 -- per-topic resilience, keep other topics
        return ""
    text = parse_summary_response(resp.content)
    cache.put(ckey, text)
    return text


def build_canvas_data(
    graph: CallGraph, llm, cache_dir: Path | None = None
) -> dict | None:
    """Run the full canvas pipeline; return the embeddable ``canvas`` dict.

    Returns ``None`` when the flow has no summarizable source (nothing to render).
    """
    lines, line_meta = build_flow_document(graph)
    if not lines:
        return None

    cache = _Cache(cache_dir)

    groups = _query_topic_groups(lines, llm, cache)

    # Order topics by their first covered unit so they read in document order.
    def _first_unit(g: dict) -> int:
        return min((r["start"] for r in g["ranges"]), default=0)

    groups.sort(key=_first_unit)

    topics: list[dict] = []
    for g in groups:
        label = g["label"]
        path = ">".join(label)
        ranges = [{"start": r["start"], "end": r["end"]} for r in g["ranges"]]
        summary = _summarize_topic(path, ranges, lines, llm, cache)
        topics.append(
            {
                "path": path,
                "name": label[-1] if label else path,
                "level": len(label),
                "ranges": ranges,
                "lineNumbers": _ranges_to_line_numbers(ranges),
                "summary": summary,
            }
        )

    return {
        "lines": lines,
        "lineMeta": line_meta,
        "topics": topics,
        "stats": {"lineCount": len(lines), "topicCount": len(topics)},
    }
