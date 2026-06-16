"""Tests for the Traverse backend."""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path

import pytest

from traverse.cache import SummaryCache
from traverse.config import load_config
from traverse.graph_service import GraphService, list_directory
from traverse.llm_service import reachable_from
from traverse.serialize import graph_to_response
from traverse.server import make_handler_class


@pytest.fixture
def project_tree(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        "def main():\n    helper()\n\ndef helper():\n    pass\n"
    )
    (tmp_path / "src" / "util.py").write_text("def unused():\n    pass\n")
    return tmp_path


def test_list_directory(project_tree: Path):
    result = list_directory(project_tree, "")
    paths = {e["path"] for e in result["entries"]}
    assert "src" in paths


def test_build_graph_for_file(project_tree: Path):
    service = GraphService(project_tree)
    scoped = service.build_for_file("src/main.py")
    assert scoped.scope_file == "src/main.py"
    names = {n.name for n in scoped.graph.nodes}
    assert "main" in names
    assert "helper" in names
    assert "unused" not in names


def test_reachable_from(project_tree: Path):
    service = GraphService(project_tree)
    scoped = service.build_for_file("src/main.py")
    main_id = next(n.id for n in scoped.graph.nodes if n.name == "main")
    reachable = reachable_from(scoped.graph, main_id)
    assert main_id in reachable
    helper_id = next(n.id for n in scoped.graph.nodes if n.name == "helper")
    assert helper_id in reachable


def test_graph_to_response(project_tree: Path):
    service = GraphService(project_tree)
    scoped = service.build_for_file("src/main.py")
    payload = graph_to_response(scoped.graph, scope_file=scoped.scope_file, collection_root=".")
    assert payload["scope_file"] == "src/main.py"
    assert payload["entrypoints"]
    assert payload["stats"]["nodes"] >= 2


def test_summary_cache_roundtrip(tmp_path: Path):
    cache = SummaryCache(tmp_path / "cache")
    key = cache.make_key(
        scope_file="a.py",
        start_stable_key="a.py::main",
        reachable_signature="abc",
        mtimes_signature="def",
    )
    cache.set(key, {"summary": "test flow"})
    assert cache.get(key) == {"summary": "test flow"}


def test_api_health_and_graph(project_tree: Path):
    config = load_config(project_tree)
    graph_service = GraphService(project_tree)
    handler_cls = make_handler_class(config, graph_service, None)
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/api/health")
        resp = conn.getresponse()
        data = json.loads(resp.read().decode())
        assert data["ok"] is True
        assert data["project_root"] == str(project_tree.resolve())

        body = json.dumps({"file": "src/main.py"}).encode()
        conn.request(
            "POST",
            "/api/graph",
            body,
            {"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        graph_data = json.loads(resp.read().decode())
        assert resp.status == 200
        assert graph_data["entrypoints"]
    finally:
        server.shutdown()
