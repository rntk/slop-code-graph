"""Glue the pruned flow's function bodies into one line-oriented document.

The canvas pipeline treats each physical line of source as a unit (the analogue
of a sentence in the article pipeline). We concatenate the bodies of the
in-project functions that participate in the flow, separating each with a
synthetic header line so topic boundaries align with function boundaries.

Ordering is **call sequence**, not a sort: we walk the graph depth-first from its
entrypoints (callee-ward), so a contiguous span of the document maps onto an
actual flow through the code. Each header is enriched with the graph signal the
LLM cannot otherwise see from raw text — the function's flow depth, its callers
and callees, and (on a file's first appearance) that file's role — so topic
grouping can follow real relationships instead of mere text adjacency.
"""

from __future__ import annotations

from src.graph_builder import CallGraph

# Cap how many caller/callee names we list on a header so it stays one terse line
# even for hub functions with many neighbours.
_MAX_NEIGHBOURS = 6


def _ordered_nodes(graph: CallGraph) -> list:
    """Return in-project nodes in DFS-from-entrypoints (call-sequence) order.

    We descend callee-ward, visiting each node's callees in edge order, so the
    document reads as the flow executes. Entrypoints lead (sorted by file/line for
    determinism); any node not reached from an entrypoint (e.g. trapped in a
    cycle) is appended afterwards in the old shallow-first sort so nothing is
    dropped.
    """
    in_project = {
        n.id: n for n in graph.nodes if getattr(n, "language", None) != "external"
    }

    # Callees in edge order, restricted to in-project targets.
    outgoing: dict[str, list[str]] = {}
    for e in graph.edges:
        if e.source in in_project and e.target in in_project:
            outgoing.setdefault(e.source, []).append(e.target)

    def _seed_key(n) -> tuple:
        return (
            getattr(n, "relative_file", "") or getattr(n, "file", ""),
            getattr(n, "start_line", 0),
        )

    roots = sorted(
        (n for n in in_project.values() if getattr(n, "is_entrypoint", False)),
        key=_seed_key,
    )

    ordered: list = []
    visited: set[str] = set()

    def _visit(nid: str) -> None:
        # Iterative DFS to avoid recursion limits on deep flows.
        stack = [nid]
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            ordered.append(in_project[cur])
            # Push callees reversed so they are popped in edge order.
            for tid in reversed(outgoing.get(cur, [])):
                if tid not in visited:
                    stack.append(tid)

    for r in roots:
        _visit(r.id)

    # Anything unreached (cycles with no in-edge-free seed, or no entrypoints at
    # all): append in the original shallow-first, file, position order.
    leftovers = sorted(
        (n for nid, n in in_project.items() if nid not in visited),
        key=lambda n: (
            getattr(n, "depth", 0),
            getattr(n, "relative_file", "") or getattr(n, "file", ""),
            getattr(n, "start_line", 0),
        ),
    )
    ordered.extend(leftovers)
    return ordered


def _neighbour_names(ids: list[str], node_by_id: dict) -> list[str]:
    """Compact, de-duplicated display names for a set of neighbour node ids."""
    names: list[str] = []
    seen: set[str] = set()
    for nid in ids:
        n = node_by_id.get(nid)
        name = (getattr(n, "name", None) if n else None) or (
            nid.split("::")[-1] if nid.startswith("external::") else nid
        )
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def build_flow_document(
    graph: CallGraph, file_summaries: dict[str, str] | None = None
) -> tuple[list[str], list[dict]]:
    """Return ``(lines, line_meta)`` for the glued flow document.

    ``lines[i]`` is one physical line; ``line_meta[i]`` describes its origin and
    is parallel (same length, same index). External nodes have no body and are
    skipped. ``file_summaries`` (keyed by ``relative_file``) is optional; when
    given, each file's role is attached to that file's first header line. See
    ``src/canvas/CONTRACT.md`` for the field shapes.
    """
    file_summaries = file_summaries or {}

    # Neighbour lookups across the WHOLE graph (including external callees, which
    # are useful context even though they contribute no body).
    node_by_id = {n.id: n for n in graph.nodes}
    callees: dict[str, list[str]] = {}
    callers: dict[str, list[str]] = {}
    for e in graph.edges:
        callees.setdefault(e.source, []).append(e.target)
        callers.setdefault(e.target, []).append(e.source)

    nodes = _ordered_nodes(graph)

    lines: list[str] = []
    line_meta: list[dict] = []
    files_seen: set[str] = set()

    for n in nodes:
        body = (getattr(n, "source_code", "") or "").rstrip("\n")
        if not body.strip():
            continue
        rel = getattr(n, "relative_file", "") or getattr(n, "file", "") or ""
        qn = getattr(n, "qualified_name", None) or getattr(n, "name", "fn")
        start = getattr(n, "start_line", 0) or 0
        end = getattr(n, "end_line", 0) or 0
        depth = getattr(n, "depth", 0) or 0

        # Enriched header — one unit, marks the function boundary AND carries the
        # graph signal (depth + call relationships) the LLM can't see from text.
        header = f"=== {rel} :: {qn} (L{start}-{end}) | depth={depth}"
        out_names = _neighbour_names(callees.get(n.id, []), node_by_id)
        if out_names:
            shown = ", ".join(out_names[:_MAX_NEIGHBOURS])
            extra = "…" if len(out_names) > _MAX_NEIGHBOURS else ""
            header += f" | calls: {shown}{extra}"
        in_names = _neighbour_names(callers.get(n.id, []), node_by_id)
        if in_names:
            shown = ", ".join(in_names[:_MAX_NEIGHBOURS])
            extra = "…" if len(in_names) > _MAX_NEIGHBOURS else ""
            header += f" | called-by: {shown}{extra}"
        # File role: attach once, on the file's first appearance, so the model
        # gets module context without repeating it on every function.
        if rel not in files_seen:
            files_seen.add(rel)
            role = (file_summaries.get(rel) or "").strip()
            if role:
                header += f" | file role: {role}"
        header += " ==="

        lines.append(header)
        line_meta.append(
            {
                "kind": "header",
                "nodeId": getattr(n, "id", ""),
                "stableKey": getattr(n, "stable_key", ""),
                "relativeFile": rel,
                "qualifiedName": qn,
                "fileLine": 0,
            }
        )

        for offset, code_line in enumerate(body.split("\n")):
            lines.append(code_line)
            line_meta.append(
                {
                    "kind": "code",
                    "nodeId": getattr(n, "id", ""),
                    "stableKey": getattr(n, "stable_key", ""),
                    "relativeFile": rel,
                    "qualifiedName": qn,
                    "fileLine": (start + offset) if start else 0,
                }
            )

    return lines, line_meta
