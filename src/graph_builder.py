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

    # ── Flow-model metadata (set by compute_flow_metadata) ──────────────────
    # A node is an *entrypoint* when it sits at the start of a flow: it belongs
    # to the selected scope (the file/dir the user pointed at) and nothing in
    # the pruned graph calls it. ``depth`` is the shortest call-distance from
    # any entrypoint, so a flow can be walked breadth-first from its roots.
    is_entrypoint: bool = False
    depth: int = 0
    # Line-independent identity, stable across edits to the file body. Intended
    # as the key under which a later pass attaches LLM-generated descriptions so
    # the annotation survives when line numbers shift. Format:
    # "<relative_file>::<qualified_name>" (or "external::<name>").
    stable_key: str = ""

    # ── LLM enrichment slots (populated by a later, separate pass) ──────────
    # Left empty by the deterministic graph build. A future semantic pass walks
    # the flow and fills these in; the renderer surfaces them when present.
    summary: str = ""  # one-line role of this function in the flow
    description: str = ""  # longer narrative / notes


@dataclass
class GraphEdge:
    id: str
    source: str
    target: str
    confidence: str  # "definite" | "possible"
    # LLM enrichment slot: a short label for what this call *means* in the flow
    # (e.g. "validates input", "persists record"). Empty until enriched.
    semantic_label: str = ""


@dataclass
class CallGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)


def _disambiguate(caller: FunctionInfo, candidates: list[FunctionInfo]) -> list[FunctionInfo]:
    """Narrow an ambiguous call to its most likely real target(s).

    A call name is matched against every definition with that name across the
    whole collected project. Without narrowing, an unqualified call resolves to
    *all* of them — so a function calling a locally-defined ``validate`` also
    gets a spurious edge to an unrelated ``validate`` in another file. When the
    caller's own file defines the called name, lexical scope makes that local
    definition the real target, so we restrict to it; same-named functions
    elsewhere are unrelated. No-op unless it leaves at least one candidate, so a
    purely cross-file call is never lost.
    """
    if len(candidates) <= 1:
        return candidates

    same_file = [c for c in candidates if c.file == caller.file]
    if same_file:
        return same_file

    return candidates


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
                stable_key=f"{rel}::{fn.qualified_name}",
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
                stable_key=f"external::{name}",
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
            # A call to one of the function's own parameter names is a local
            # reference (an injected callback / dependency), not a module-level
            # function. It shadows definitions everywhere — including the same
            # file — so route it straight to the external/unresolved path instead
            # of binding it to same-named definitions (e.g. test-file mocks).
            if call_name in fn.param_names:
                if include_external:
                    _add_edge(fn.id, _external_node(call_name).id, "external")
                continue

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

            # Narrow ambiguous matches to the call's real target so unrelated
            # same-named functions (e.g. helpers in test files) aren't pulled
            # into the downstream flow as spurious callees.
            candidates = _disambiguate(fn, candidates)

            confidence = "definite" if len(candidates) == 1 else "possible"
            if confidence == "possible" and not include_possible:
                continue

            for target in candidates:
                _add_edge(fn.id, target.id, confidence)

    # Append external nodes after the real ones so layout/legend keep definitions
    # first; only those actually referenced by an edge exist in the dict.
    nodes.extend(external_nodes.values())

    return CallGraph(nodes=nodes, edges=edges)


def compute_flow_metadata(graph: CallGraph, seed_ids: set[str]) -> None:
    """Mark flow entrypoints and assign each node a depth, in place.

    A *flow* is a rooted, downstream (callee-ward) view of the graph. ``seed_ids``
    are the nodes belonging to the scope the user selected (the entry file, or
    every file under the entry directory). After the caller has pruned the graph
    to what is reachable *from* the seed, this function determines where the
    flows start and how far each node sits from a start:

      * **entrypoint** — a seed node with no incoming edge inside the pruned
        graph. These are the "you are here" roots a reader (or an LLM walking the
        flow) begins from. If every seed node has an in-edge (e.g. the whole
        scope is one big cycle) we fall back to treating all seed nodes as
        entrypoints so the flow still has a visible start.
      * **depth** — shortest call-distance from any entrypoint (BFS). Entrypoints
        are depth 0. Nodes only reachable through cycles keep depth 0 if never
        relaxed; that is acceptable for ordering hints.
    """
    node_ids = {n.id for n in graph.nodes}
    seed_ids = {nid for nid in seed_ids if nid in node_ids}

    outgoing: dict[str, list[str]] = {}
    indeg: dict[str, int] = dict.fromkeys(node_ids, 0)
    for e in graph.edges:
        if e.source in node_ids and e.target in node_ids:
            outgoing.setdefault(e.source, []).append(e.target)
            indeg[e.target] += 1

    entrypoints = {nid for nid in seed_ids if indeg[nid] == 0}
    if not entrypoints and seed_ids:
        # Whole scope is cyclic / mutually recursive — keep every seed as a root
        # so the flow still has a start to walk from.
        entrypoints = set(seed_ids)

    # BFS from all entrypoints to assign shortest depth.
    depth: dict[str, int] = dict.fromkeys(entrypoints, 0)
    frontier = list(entrypoints)
    while frontier:
        nid = frontier.pop(0)
        for tid in outgoing.get(nid, []):
            if tid not in depth:
                depth[tid] = depth[nid] + 1
                frontier.append(tid)

    for n in graph.nodes:
        n.is_entrypoint = n.id in entrypoints
        n.depth = depth.get(n.id, 0)


def _relative_path(absolute: str, base_dir: str) -> str:
    if not base_dir:
        return absolute
    try:
        from pathlib import Path

        return str(Path(absolute).relative_to(base_dir))
    except ValueError:
        return absolute
