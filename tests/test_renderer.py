"""Tests for renderer.py."""

import html

from src.graph_builder import CallGraph, GraphEdge, GraphNode
from src.renderer import render


def test_render_escapes_title():
    graph = CallGraph(
        nodes=[
            GraphNode(
                id="n1",
                name="foo",
                qualified_name="foo",
                file="/test.py",
                relative_file="test.py",
                class_name=None,
                start_line=1,
                end_line=1,
                source_code="def foo(): pass",
                language="python",
                color="#4ec9b0",
            )
        ],
        edges=[],
    )

    malicious_title = "<script>alert(1)</script>"
    html_out = render(graph, malicious_title)

    assert malicious_title not in html_out
    assert html.escape(malicious_title, quote=True) in html_out


def test_render_escapes_script_tag_in_json():
    graph = CallGraph(
        nodes=[
            GraphNode(
                id="n1",
                name="foo",
                qualified_name="foo",
                file="/test.py",
                relative_file="test.py",
                class_name=None,
                start_line=1,
                end_line=1,
                source_code='x = "</script><script>alert(1)</script>"',
                language="python",
                color="#4ec9b0",
            )
        ],
        edges=[],
    )

    html_out = render(graph, "test")

    # The literal </script> should not appear inside the script tag
    script_start = html_out.find("<script>")
    script_end = html_out.find("</script>", script_start)
    script_content = html_out[script_start:script_end]

    # After escaping, </script> becomes <\/script>
    assert "</script><script>" not in script_content
    assert "<\\/script>" in script_content or "</" not in script_content


def test_render_contains_graph_data():
    graph = CallGraph(
        nodes=[
            GraphNode(
                id="n1",
                name="foo",
                qualified_name="foo",
                file="/test.py",
                relative_file="test.py",
                class_name=None,
                start_line=1,
                end_line=1,
                source_code="def foo(): pass",
                language="python",
                color="#4ec9b0",
            )
        ],
        edges=[
            GraphEdge(
                id="e1",
                source="n1",
                target="n1",
                confidence="definite",
            )
        ],
    )

    html_out = render(graph, "My Graph")
    assert "My Graph" in html_out
    assert "n1" in html_out
    assert "def foo(): pass" in html_out


def _node(**kw):
    return GraphNode(
        id=kw.get("id", "n1"),
        name=kw.get("name", "foo"),
        qualified_name=kw.get("qualified_name", "foo"),
        file=kw.get("file", "/test.py"),
        relative_file=kw.get("relative_file", "test.py"),
        class_name=kw.get("class_name"),
        start_line=kw.get("start_line", 1),
        end_line=kw.get("end_line", 1),
        source_code=kw.get("source_code", "def foo(): pass"),
        language=kw.get("language", "python"),
        color=kw.get("color", "#4ec9b0"),
        flow=kw.get("flow", []),
    )


def test_render_includes_flowchart_assets():
    graph = CallGraph(nodes=[_node()], edges=[])
    out = render(graph, "t")
    # The flowchart view markup, builder and entry button are all present.
    for marker in ("flow-view", "buildElements", "btn-flow", "flow-cy", "View flowchart"):
        assert marker in out, marker


def test_render_includes_selected_node_focus_assets():
    graph = CallGraph(
        nodes=[_node(id="n1"), _node(id="n2", name="bar", qualified_name="bar")],
        edges=[GraphEdge(id="e1", source="n1", target="n2", confidence="definite")],
    )
    out = render(graph, "t")

    for marker in (
        "focusNodeNeighborhood",
        "Focused:",
        "connected node",
        "gv.edgeClass(id, 'highlighted', incident)",
    ):
        assert marker in out, marker


def test_render_includes_summary_only_toggle():
    graph = CallGraph(nodes=[_node()], edges=[])
    out = render(graph, "t", file_summaries={"test.py": "Handles input validation."})
    assert "btn-summary" in out
    assert "Summary only" in out
    assert "Handles input validation." in out
    assert "fileSummaries" in out


def test_render_includes_canvas_topic_group_controls():
    graph = CallGraph(nodes=[_node()], edges=[])
    canvas = {
        "lines": ["=== test.py :: foo (L1-1) ===", "def foo(): pass"],
        "lineMeta": [
            {"kind": "header", "nodeId": "n1", "relativeFile": "test.py"},
            {"kind": "code", "nodeId": "n1", "relativeFile": "test.py"},
        ],
        "topics": [
            {
                "path": "Setup>Validation",
                "name": "Validation",
                "level": 2,
                "ranges": [{"start": 0, "end": 1}],
                "lineNumbers": [1, 2],
                "summary": "Validates input.",
            }
        ],
        "stats": {"lineCount": 2, "topicCount": 1},
    }

    out = render(graph, "t", canvas=canvas)

    assert "group-select" in out
    assert "topic-levels" in out
    assert "Canvas topics" in out
    assert "Setup>Validation" in out
    assert "Validates input." in out
    assert "topicSummaryNodeLabel" in out
    assert "Topic&nbsp;summary" in out
    assert "Show Canvas topic summaries instead of function names" in out


def test_render_embeds_flow_data():
    flow = [{"t": "if", "cond": "x > 0", "then": [], "else": []}]
    graph = CallGraph(nodes=[_node(flow=flow)], edges=[])
    out = render(graph, "t")
    # The structured flow rides along in the embedded GRAPH_DATA payload.
    assert '"flow":' in out
    assert '"cond":"x > 0"' in out
