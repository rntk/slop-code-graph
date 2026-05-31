"""Build a resolved call graph from a list of FunctionInfo objects."""

from __future__ import annotations

from dataclasses import dataclass, field

from .parsers import FunctionInfo


@dataclass
class GraphNode:
    id: str
    name: str
    qualified_name: str
    file: str
    relative_file: str
    class_name: str | None
    start_line: int
    end_line: int
    source_code: str
    language: str
    color: str
    flow: list = field(default_factory=list)  # structured control-flow (flowchart)


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
    "python": "#4ec9b0",
    "javascript": "#dcdcaa",
    "typescript": "#569cd6",
    "tsx": "#4fc1ff",
    "go": "#9cdcfe",
    "java": "#ce9178",
    "cpp": "#c586c0",
    "php": "#b5cea8",
}
DEFAULT_COLOR = "#808080"
# Muted colour for synthetic "external" nodes (stdlib / builtins / 3rd-party
# calls that have no definition in the parsed set). Deliberately desaturated so
# real function definitions remain the visual focus.
EXTERNAL_COLOR = "#5a5a72"


def build_graph(
    functions: list[FunctionInfo],
    base_dir: str = "",
    include_possible: bool = True,
    include_external: bool = True,
) -> CallGraph:
    """
    Resolve function calls to edges and return a CallGraph.

    Resolution strategy:
      1. Build name → [FunctionInfo] lookup (by simple name).
      2. For each call in a function, find all definitions with that name.
      3. Confidence: "definite" if exactly one match, "possible" if multiple.
      4. Calls with no match in the parsed set are *external* (stdlib / builtin /
         third-party). When ``include_external`` is set we add one synthetic
         node per unique external name (global dedup) plus an edge to it, so the
         caller's full control flow — not just its in-project calls — is visible.
         When disabled, such calls are dropped (legacy behaviour).
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
                flow=fn.flow,
            )
        )

    # Synthetic external nodes are created lazily and deduped by call name, so
    # every call to e.g. ``print`` across the codebase converges on one node.
    external_nodes: dict[str, GraphNode] = {}

    def _external_node(name: str) -> GraphNode:
        node = external_nodes.get(name)
        if node is None:
            node = GraphNode(
                id=f"external::{name}",
                name=name,
                qualified_name=name,
                file="",
                relative_file="<external>",
                class_name=None,
                start_line=0,
                end_line=0,
                source_code="",
                language="external",
                color=EXTERNAL_COLOR,
            )
            external_nodes[name] = node
        return node

    # Build edges
    edges: list[GraphEdge] = []
    seen_edges: set[tuple[str, str]] = set()
    edge_counter = 0

    def _add_edge(source: str, target: str, confidence: str) -> None:
        nonlocal edge_counter
        key = (source, target)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append(
            GraphEdge(
                id=f"e{edge_counter}",
                source=source,
                target=target,
                confidence=confidence,
            )
        )
        edge_counter += 1

    for fn in functions:
        for call_name in fn.calls:
            # call_name is always a *simple* identifier (the last segment of the
            # callee expression). Prefer a free function whose qualified name is
            # exactly that simple name (an unqualified call is more likely a free
            # function than a method); only fall back to the broader by-name set
            # — which also includes methods "Class.<name>" — when none exists.
            candidates = by_qualified.get(call_name, [])
            if not candidates:
                candidates = by_name.get(call_name, [])

            # No definition in the parsed set → external call.
            if not candidates:
                if include_external:
                    _add_edge(fn.id, _external_node(call_name).id, "external")
                continue

            # Drop calls that resolve only to themselves (unless they ARE recursive)
            candidates = [c for c in candidates if c.id != fn.id or len(candidates) == 1]

            confidence = "definite" if len(candidates) == 1 else "possible"
            if confidence == "possible" and not include_possible:
                continue

            for target in candidates:
                _add_edge(fn.id, target.id, confidence)

    # Append external nodes after the real ones so layout/legend keep definitions
    # first; only those actually referenced by an edge exist in the dict.
    nodes.extend(external_nodes.values())

    return CallGraph(nodes=nodes, edges=edges)


def _relative_path(absolute: str, base_dir: str) -> str:
    if not base_dir:
        return absolute
    try:
        from pathlib import Path

        return str(Path(absolute).relative_to(base_dir))
    except ValueError:
        return absolute
