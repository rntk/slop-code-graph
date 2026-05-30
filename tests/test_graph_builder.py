"""Tests for graph_builder.py."""

from src.parsers import FunctionInfo
from src.graph_builder import build_graph, GraphNode, GraphEdge, CallGraph


def make_fn(**kwargs):
    defaults = {
        "id": "f1",
        "name": "foo",
        "qualified_name": "foo",
        "file": "/test.py",
        "class_name": None,
        "start_line": 1,
        "end_line": 1,
        "source_code": "def foo(): pass",
        "language": "python",
        "calls": [],
    }
    defaults.update(kwargs)
    return FunctionInfo(**defaults)


def test_build_graph_basic():
    f1 = make_fn(id="f1", name="foo", calls=["bar"])
    f2 = make_fn(id="f2", name="bar", calls=[])

    graph = build_graph([f1, f2])

    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1
    assert graph.edges[0].source == "f1"
    assert graph.edges[0].target == "f2"
    assert graph.edges[0].confidence == "definite"


def test_build_graph_possible_edges():
    f1 = make_fn(id="f1", name="foo", calls=["baz"])
    f2 = make_fn(id="f2", name="baz", calls=[])
    f3 = make_fn(id="f3", name="baz", calls=[])

    graph = build_graph([f1, f2, f3])

    # Two possible edges because baz is ambiguous
    assert len(graph.edges) == 2
    assert all(e.confidence == "possible" for e in graph.edges)


def test_build_graph_no_possible_filter():
    f1 = make_fn(id="f1", name="foo", calls=["baz"])
    f2 = make_fn(id="f2", name="baz", calls=[])
    f3 = make_fn(id="f3", name="baz", calls=[])

    graph = build_graph([f1, f2, f3], include_possible=False)

    assert len(graph.edges) == 0


def test_build_graph_self_call_not_dropped_when_unique():
    f1 = make_fn(id="f1", name="foo", calls=["foo"])

    graph = build_graph([f1])

    assert len(graph.edges) == 1
    assert graph.edges[0].source == "f1"
    assert graph.edges[0].target == "f1"
    assert graph.edges[0].confidence == "definite"


def test_build_graph_self_call_dropped_when_ambiguous():
    f1 = make_fn(id="f1", name="foo", calls=["foo"])
    f2 = make_fn(id="f2", name="foo", calls=[])

    graph = build_graph([f1, f2])

    # f1 calls "foo" but there are two definitions (f1 and f2).
    # The candidate list filters out f1 unless it's the only match,
    # so the edge should go to f2 only.
    edges_to_f1 = [e for e in graph.edges if e.target == "f1"]
    edges_to_f2 = [e for e in graph.edges if e.target == "f2"]
    assert len(edges_to_f1) == 0
    assert len(edges_to_f2) == 1
    assert edges_to_f2[0].confidence == "definite"


def test_build_graph_qualified_match():
    f1 = make_fn(id="f1", name="foo", calls=["MyClass.method"])
    f2 = make_fn(id="f2", name="method", qualified_name="MyClass.method", class_name="MyClass")

    graph = build_graph([f1, f2])

    assert len(graph.edges) == 1
    assert graph.edges[0].target == "f2"
    assert graph.edges[0].confidence == "definite"


def test_build_graph_external_call_creates_node():
    f1 = make_fn(id="f1", name="foo", calls=["print"])

    graph = build_graph([f1])

    # One real node + one synthetic external node for "print"
    assert len(graph.nodes) == 2
    ext = [n for n in graph.nodes if n.language == "external"]
    assert len(ext) == 1
    assert ext[0].name == "print"
    assert ext[0].id == "external::print"

    assert len(graph.edges) == 1
    assert graph.edges[0].source == "f1"
    assert graph.edges[0].target == "external::print"
    assert graph.edges[0].confidence == "external"


def test_build_graph_external_nodes_deduped():
    f1 = make_fn(id="f1", name="foo", calls=["print"])
    f2 = make_fn(id="f2", name="bar", calls=["print"])

    graph = build_graph([f1, f2])

    # Both callers converge on a single external "print" node
    ext = [n for n in graph.nodes if n.language == "external"]
    assert len(ext) == 1
    ext_edges = [e for e in graph.edges if e.confidence == "external"]
    assert len(ext_edges) == 2
    assert {e.source for e in ext_edges} == {"f1", "f2"}
    assert all(e.target == "external::print" for e in ext_edges)


def test_build_graph_no_external_filter():
    f1 = make_fn(id="f1", name="foo", calls=["print", "bar"])
    f2 = make_fn(id="f2", name="bar", calls=[])

    graph = build_graph([f1, f2], include_external=False)

    # "print" is dropped; only the in-project edge to bar remains
    assert all(n.language != "external" for n in graph.nodes)
    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1
    assert graph.edges[0].target == "f2"
