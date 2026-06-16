"""Core rendering logic: turns a CallGraph into a self-contained HTML string.

This module is intentionally small; the bulk of the output (the embedded
browser-side engine and UI) lives under src/renderer/assets so that the
visual pieces remain composable and easier to navigate/edit.
"""

from __future__ import annotations

import html
import json

from ..graph_builder import CallGraph
from .assets import app as app_assets
from .assets import engine as engine_assets
from .assets import flow as flow_assets
from .assets import treemap as treemap_assets
from .templates import HTML_TEMPLATE


def _serialize_graph(graph: CallGraph) -> str:
    """Convert the CallGraph to a compact JSON string for embedding.

    The produced JSON is placed into the @@GRAPHDATA@@ placeholder inside
    APP_SCRIPT. We also perform the minimal escaping required to keep a
    literal "</script>" from ever appearing inside the surrounding <script>.
    """
    nodes_data = [
        {
            "id": n.id,
            "name": n.name,
            "qualified_name": n.qualified_name,
            "file": n.file,
            "relative_file": n.relative_file,
            "class_name": n.class_name,
            "start_line": n.start_line,
            "end_line": n.end_line,
            "source_code": n.source_code,
            "language": n.language,
            "color": n.color,
            "flow": n.flow or [],
            "is_entrypoint": n.is_entrypoint,
            "depth": n.depth,
            "stable_key": n.stable_key,
            "summary": n.summary,
            "description": n.description,
        }
        for n in graph.nodes
    ]

    edges_data = [
        {
            "id": e.id,
            "source": e.source,
            "target": e.target,
            "confidence": e.confidence,
            "semantic_label": e.semantic_label,
        }
        for e in graph.edges
    ]

    graph_data_json = json.dumps(
        {"nodes": nodes_data, "edges": edges_data},
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    return graph_data_json


def render(graph: CallGraph, title: str) -> str:
    """Render a CallGraph to a fully self-contained, dependency-free HTML string."""
    graph_data_json = _serialize_graph(graph)

    # Token replacement (not str.format) so embedded CSS/JS braces need no
    # escaping. Scripts are injected first; the (escaped) graph data goes last
    # to fill the @@GRAPHDATA@@ placeholder carried in by APP_SCRIPT.
    out = HTML_TEMPLATE
    out = out.replace("@@ENGINE@@", engine_assets.ENGINE_SCRIPT)
    out = out.replace("@@APP@@", app_assets.APP_SCRIPT)
    out = out.replace("@@FLOWSTYLE@@", flow_assets.FLOW_STYLE)
    out = out.replace("@@FLOWSCRIPT@@", flow_assets.FLOW_SCRIPT)
    out = out.replace("@@TREEMAPSTYLE@@", treemap_assets.TREEMAP_STYLE)
    out = out.replace("@@TREEMAPSCRIPT@@", treemap_assets.TREEMAP_SCRIPT)
    out = out.replace("@@TITLE@@", html.escape(title, quote=True))
    out = out.replace("@@GRAPHDATA@@", graph_data_json)
    return out
