"""Tests for renderer.py."""

import html

from src.graph_builder import CallGraph, GraphNode, GraphEdge
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

    malicious_title = '<script>alert(1)</script>'
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
