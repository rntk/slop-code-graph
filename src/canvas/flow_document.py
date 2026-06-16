"""Glue the pruned flow's function bodies into one line-oriented document.

The canvas pipeline treats each physical line of source as a unit (the analogue
of a sentence in the article pipeline). We concatenate the bodies of the
in-project functions that participate in the flow — ordered by flow depth, then
file, then position — separating each with a synthetic header line so topic
boundaries align with function boundaries.
"""

from __future__ import annotations

from src.graph_builder import CallGraph


def build_flow_document(graph: CallGraph) -> tuple[list[str], list[dict]]:
    """Return ``(lines, line_meta)`` for the glued flow document.

    ``lines[i]`` is one physical line; ``line_meta[i]`` describes its origin and
    is parallel (same length, same index). External nodes have no body and are
    skipped. See ``src/canvas/CONTRACT.md`` for the field shapes.
    """
    nodes = [n for n in graph.nodes if getattr(n, "language", None) != "external"]
    # Flow order: shallow first (entrypoints lead), then group by file, then by
    # source position so a file's functions read top-to-bottom.
    nodes.sort(
        key=lambda n: (
            getattr(n, "depth", 0),
            getattr(n, "relative_file", "") or getattr(n, "file", ""),
            getattr(n, "start_line", 0),
        )
    )

    lines: list[str] = []
    line_meta: list[dict] = []

    for n in nodes:
        body = (getattr(n, "source_code", "") or "").rstrip("\n")
        if not body.strip():
            continue
        rel = getattr(n, "relative_file", "") or getattr(n, "file", "") or ""
        qn = getattr(n, "qualified_name", None) or getattr(n, "name", "fn")
        start = getattr(n, "start_line", 0) or 0
        end = getattr(n, "end_line", 0) or 0

        # Synthetic separator line — one unit, marks the function boundary.
        lines.append(f"=== {rel} :: {qn} (L{start}-{end}) ===")
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
