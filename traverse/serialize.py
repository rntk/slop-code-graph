"""Wire-format serialization for CallGraph API responses."""

from __future__ import annotations

from src.graph_builder import CallGraph, GraphEdge, GraphNode


def node_to_dict(node: GraphNode) -> dict:
    return {
        "id": node.id,
        "name": node.name,
        "qualified_name": node.qualified_name,
        "file": node.file,
        "relative_file": node.relative_file,
        "class_name": node.class_name,
        "start_line": node.start_line,
        "end_line": node.end_line,
        "language": node.language,
        "stable_key": node.stable_key,
        "is_entrypoint": node.is_entrypoint,
        "depth": node.depth,
        "source_code": node.source_code,
        "summary": node.summary,
        "description": node.description,
    }


def edge_to_dict(edge: GraphEdge) -> dict:
    return {
        "id": edge.id,
        "source": edge.source,
        "target": edge.target,
        "confidence": edge.confidence,
        "semantic_label": edge.semantic_label,
    }


def graph_to_response(
    graph: CallGraph,
    *,
    scope_file: str,
    collection_root: str,
) -> dict:
    entrypoints = [n.id for n in graph.nodes if n.is_entrypoint]
    return {
        "scope_file": scope_file,
        "collection_root": collection_root,
        "nodes": [node_to_dict(n) for n in graph.nodes],
        "edges": [edge_to_dict(e) for e in graph.edges],
        "entrypoints": entrypoints,
        "stats": {"nodes": len(graph.nodes), "edges": len(graph.edges)},
    }
