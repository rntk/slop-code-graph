"""Build a resolved call graph from a list of FunctionInfo objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .parsers import FunctionInfo


@dataclass
class GraphNode:
    id: str
    name: str
    qualified_name: str
    file: str
    relative_file: str
    class_name: Optional[str]
    start_line: int
    end_line: int
    source_code: str
    language: str
    color: str


@dataclass
class GraphEdge:
    id: str
    source: str
    target: str
    confidence: str  # "definite" | "possible"


@dataclass
class CallGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)


LANGUAGE_COLORS = {
    "python":     "#4ec9b0",
    "javascript": "#dcdcaa",
    "typescript": "#569cd6",
    "tsx":        "#4fc1ff",
    "go":         "#9cdcfe",
    "java":       "#ce9178",
    "cpp":        "#c586c0",
    "php":        "#b5cea8",
}
DEFAULT_COLOR = "#808080"


def build_graph(functions: list[FunctionInfo], base_dir: str = "") -> CallGraph:
    """
    Resolve function calls to edges and return a CallGraph.

    Resolution strategy:
      1. Build name → [FunctionInfo] lookup (by simple name).
      2. For each call in a function, find all definitions with that name.
      3. Confidence: "definite" if exactly one match, "possible" if multiple.
      4. Calls with no match in the parsed set are dropped (external/stdlib).
    """
    # Index by simple name and by qualified name
    by_name: dict[str, list[FunctionInfo]] = {}
    by_qualified: dict[str, list[FunctionInfo]] = {}
    for fn in functions:
        by_name.setdefault(fn.name, []).append(fn)
        by_qualified.setdefault(fn.qualified_name, []).append(fn)

    # Build nodes
    nodes: list[GraphNode] = []
    for fn in functions:
        rel = _relative_path(fn.file, base_dir)
        nodes.append(
            GraphNode(
                id=fn.id,
                name=fn.name,
                qualified_name=fn.qualified_name,
                file=fn.file,
                relative_file=rel,
                class_name=fn.class_name,
                start_line=fn.start_line,
                end_line=fn.end_line,
                source_code=fn.source_code,
                language=fn.language,
                color=LANGUAGE_COLORS.get(fn.language, DEFAULT_COLOR),
            )
        )

    # Build edges
    edges: list[GraphEdge] = []
    seen_edges: set[tuple[str, str]] = set()
    edge_counter = 0

    for fn in functions:
        for call_name in fn.calls:
            # Try qualified match first (e.g. "ClassName.method")
            candidates = by_qualified.get(call_name, [])
            if not candidates:
                candidates = by_name.get(call_name, [])
            # Drop calls that resolve only to themselves (unless they ARE recursive)
            candidates = [c for c in candidates if c.id != fn.id or len(candidates) == 1]

            confidence = "definite" if len(candidates) == 1 else "possible"

            for target in candidates:
                key = (fn.id, target.id)
                if key in seen_edges:
                    continue
                seen_edges.add(key)
                edges.append(
                    GraphEdge(
                        id=f"e{edge_counter}",
                        source=fn.id,
                        target=target.id,
                        confidence=confidence,
                    )
                )
                edge_counter += 1

    return CallGraph(nodes=nodes, edges=edges)


def _relative_path(absolute: str, base_dir: str) -> str:
    if not base_dir:
        return absolute
    try:
        from pathlib import Path
        return str(Path(absolute).relative_to(base_dir))
    except ValueError:
        return absolute
