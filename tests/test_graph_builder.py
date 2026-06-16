"""Tests for graph_builder.py."""

from src.graph_builder import build_graph, compute_flow_metadata
from src.parsers import FunctionInfo


def make_fn(**kwargs):
    return FunctionInfo(
        id=kwargs.get("id", "f1"),
        name=kwargs.get("name", "foo"),
        qualified_name=kwargs.get("qualified_name", "foo"),
        file=kwargs.get("file", "/test.py"),
        class_name=kwargs.get("class_name"),
        start_line=kwargs.get("start_line", 1),
        end_line=kwargs.get("end_line", 1),
        source_code=kwargs.get("source_code", "def foo(): pass"),
        language=kwargs.get("language", "python"),
        calls=kwargs.get("calls", []),
        flow=kwargs.get("flow", []),
        param_names=kwargs.get("param_names", set()),
    )


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


def test_disambiguate_prefers_same_file():
    # caller and one `bar` live in /a.py; a colliding `bar` lives in /b.py.
    # The same-file definition is the real (lexically scoped) target.
    caller = make_fn(id="c", name="foo", calls=["bar"], file="/a.py")
    local = make_fn(id="local", name="bar", file="/a.py")
    other = make_fn(id="other", name="bar", file="/b.py")

    graph = build_graph([caller, local, other])

    edges = [e for e in graph.edges if e.source == "c"]
    assert len(edges) == 1
    assert edges[0].target == "local"
    assert edges[0].confidence == "definite"


def test_call_to_own_parameter_is_not_resolved_in_project():
    # `confirm` is a parameter (injected callback) of `handler`; calling it must
    # not bind to module-level `confirm` definitions elsewhere (e.g. test mocks).
    handler = make_fn(
        id="h", name="handler", calls=["confirm"], file="/main.js", param_names={"confirm"}
    )
    mock = make_fn(id="m", name="confirm", file="/main.test.js")

    graph = build_graph([handler, mock], include_external=True)

    # No in-project edge to the same-named definition…
    assert not [e for e in graph.edges if e.target == "m"]
    # …the call surfaces as an external/unresolved reference instead.
    ext = [e for e in graph.edges if e.confidence == "external" and e.source == "h"]
    assert len(ext) == 1
    assert ext[0].target == "external::confirm"


def test_call_to_own_parameter_shadows_same_file_definition():
    # Parameter shadowing applies within the same file too.
    handler = make_fn(
        id="h", name="handler", calls=["cb"], file="/a.js", param_names={"cb"}
    )
    same_file_cb = make_fn(id="cb", name="cb", file="/a.js")

    graph = build_graph([handler, same_file_cb], include_external=False)

    assert not [e for e in graph.edges if e.target == "cb"]


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


def test_flow_propagated_to_node():
    flow = [{"t": "loop", "kind": "for", "label": "for i", "body": [], "do": False}]
    fn = make_fn(id="f1", name="foo", flow=flow)
    graph = build_graph([fn], include_external=False)
    node = next(n for n in graph.nodes if n.id == "f1")
    assert node.flow == flow


def test_external_nodes_have_empty_flow():
    f1 = make_fn(id="f1", name="foo", calls=["printf"])
    graph = build_graph([f1], include_external=True)
    ext = next(n for n in graph.nodes if n.language == "external")
    assert ext.flow == []


def test_stable_key_is_line_independent():
    fn = make_fn(id="x::foo::99", name="foo", qualified_name="foo", file="/a/b.py")
    graph = build_graph([fn], base_dir="/a")
    node = next(n for n in graph.nodes if n.name == "foo")
    assert node.stable_key == "b.py::foo"


def test_flow_metadata_entrypoint_and_depth():
    # f1 -> f2 -> f3 ; f1 is the only root.
    f1 = make_fn(id="f1", name="a", qualified_name="a", calls=["b"])
    f2 = make_fn(id="f2", name="b", qualified_name="b", calls=["c"])
    f3 = make_fn(id="f3", name="c", qualified_name="c", calls=[])
    graph = build_graph([f1, f2, f3])

    compute_flow_metadata(graph, {"f1", "f2", "f3"})
    by_id = {n.id: n for n in graph.nodes}

    assert by_id["f1"].is_entrypoint is True
    assert by_id["f2"].is_entrypoint is False
    assert by_id["f3"].is_entrypoint is False
    assert by_id["f1"].depth == 0
    assert by_id["f2"].depth == 1
    assert by_id["f3"].depth == 2


def test_flow_metadata_excludes_out_of_scope_callers_from_roots():
    # caller (out of scope) -> entry -> helper. Only `entry` is seeded, so it is
    # the entrypoint even though something calls it.
    entry = make_fn(id="entry", name="entry", qualified_name="entry", calls=["helper"])
    helper = make_fn(id="helper", name="helper", qualified_name="helper", calls=[])
    caller = make_fn(id="caller", name="caller", qualified_name="caller", calls=["entry"])
    graph = build_graph([entry, helper, caller])

    # Seed is only the entry node (as graph.py would after pruning to scope).
    compute_flow_metadata(graph, {"entry"})
    by_id = {n.id: n for n in graph.nodes}

    assert by_id["entry"].is_entrypoint is True
    # caller is not seeded, so it is never an entrypoint even with in-degree 0.
    assert by_id["caller"].is_entrypoint is False


def test_flow_metadata_all_cyclic_scope_falls_back_to_all_seeds():
    # Mutually recursive pair with no acyclic root.
    f1 = make_fn(id="f1", name="a", qualified_name="a", calls=["b"])
    f2 = make_fn(id="f2", name="b", qualified_name="b", calls=["a"])
    graph = build_graph([f1, f2])

    compute_flow_metadata(graph, {"f1", "f2"})
    assert all(n.is_entrypoint for n in graph.nodes)
