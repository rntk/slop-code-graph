"""Build and cache pruned downstream call graphs for file scopes."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from graph import (
    IGNORE_DIRS,
    PROJECT_MARKERS,
    SUPPORTED_EXTENSIONS,
    collect_files,
    find_collection_root,
)
from src.graph_builder import CallGraph, GraphNode, compute_flow_metadata
from src.parsers import get_registry, parse_files


@dataclass
class ScopedGraph:
    scope_file: str
    collection_root: Path
    graph: CallGraph
    node_by_id: dict[str, GraphNode]


class GraphService:
    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root.resolve()
        self._cache: dict[str, ScopedGraph] = {}
        self._lock = threading.Lock()
        self._parsers_loaded = False

    def _ensure_parsers(self) -> None:
        if not self._parsers_loaded:
            get_registry()
            self._parsers_loaded = True

    def _normalize_scope_file(self, relative_file: str) -> str:
        rel = relative_file.strip().lstrip("./")
        if not rel:
            raise ValueError("file path is required")
        target = (self._project_root / rel).resolve()
        if not target.is_file():
            raise FileNotFoundError(f"file not found: {rel}")
        if target.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"unsupported file type: {target.suffix}")
        try:
            return str(target.relative_to(self._project_root))
        except ValueError as exc:
            raise ValueError("file is outside project root") from exc

    def build_for_file(self, relative_file: str) -> ScopedGraph:
        scope_file = self._normalize_scope_file(relative_file)
        with self._lock:
            cached = self._cache.get(scope_file)
            if cached is not None:
                return cached

        self._ensure_parsers()
        target = self._project_root / scope_file
        collect_from = find_collection_root(target)
        files = collect_files(collect_from)
        if not files:
            raise ValueError("no supported source files found in collection root")

        functions = parse_files(files)
        base_dir = str(collect_from)
        from src.graph_builder import build_graph

        graph = build_graph(
            functions,
            base_dir,
            include_possible=True,
            include_external=True,
        )

        scope_files = {str(target.resolve())}
        seed_ids = {n.id for n in graph.nodes if n.file in scope_files}

        outgoing: dict[str, list[str]] = {}
        for edge in graph.edges:
            outgoing.setdefault(edge.source, []).append(edge.target)

        reachable: set[str] = set(seed_ids)
        frontier = list(reachable)
        while frontier:
            nid = frontier.pop()
            for tid in outgoing.get(nid, []):
                if tid not in reachable:
                    reachable.add(tid)
                    frontier.append(tid)

        graph.nodes = [n for n in graph.nodes if n.id in reachable]
        graph.edges = [e for e in graph.edges if e.source in reachable and e.target in reachable]
        compute_flow_metadata(graph, seed_ids & reachable)

        scoped = ScopedGraph(
            scope_file=scope_file,
            collection_root=collect_from,
            graph=graph,
            node_by_id={n.id: n for n in graph.nodes},
        )
        with self._lock:
            self._cache[scope_file] = scoped
        return scoped

    def get_cached(self, scope_file: str) -> ScopedGraph | None:
        rel = scope_file.strip().lstrip("./")
        with self._lock:
            return self._cache.get(rel)


def list_directory(project_root: Path, relative_dir: str) -> dict:
    rel = relative_dir.strip().lstrip("./") or "."
    base = (project_root / rel).resolve()
    if not base.is_dir():
        raise FileNotFoundError(f"directory not found: {rel}")
    try:
        base.relative_to(project_root.resolve())
    except ValueError as exc:
        raise ValueError("directory is outside project root") from exc

    entries: list[dict] = []
    for child in sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if child.name.startswith(".") and child.name not in PROJECT_MARKERS:
            continue
        if child.is_dir():
            if child.name in IGNORE_DIRS:
                continue
            try:
                path = str(child.relative_to(project_root.resolve()))
            except ValueError:
                continue
            entries.append({"path": path, "type": "dir"})
        elif child.is_file() and child.suffix.lower() in SUPPORTED_EXTENSIONS:
            try:
                path = str(child.relative_to(project_root.resolve()))
            except ValueError:
                continue
            entries.append({"path": path, "type": "file", "ext": child.suffix.lower()})

    return {"root": rel if rel != "." else ".", "entries": entries}
