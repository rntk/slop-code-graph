#!/usr/bin/env python3
"""
Call Graph Generator
Usage:
  python graph.py <file_or_directory> -o graph.html
  python graph.py src/main.py -o out.html
  python graph.py ./my_project -o out.html
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.graph_builder import build_graph, compute_flow_metadata
from src.parsers import get_registry, parse_files
from src.renderer import render

SUPPORTED_EXTENSIONS = {
    ".py",
    ".js",
    ".mjs",
    ".cjs",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".java",
    ".c",
    ".cpp",
    ".cc",
    ".cxx",
    ".h",
    ".hpp",
    ".hxx",
    ".c++",
    ".php",
}

IGNORE_DIRS = {
    ".git",
    ".svn",
    ".hg",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    "venv",
    ".venv",
    "env",
    ".env",
    "dist",
    "build",
    "target",
    "vendor",
    ".idea",
    ".vscode",
}

# Files/dirs whose presence marks a project root. We collect the whole project
# (up to the nearest marker) so that, whatever scope the user selects, the
# *callers* living elsewhere in the project are visible — and can therefore be
# pruned out — giving a directory the same downstream-only flow a single file
# already gets. Ordered by how strongly each implies a root.
PROJECT_MARKERS = {
    ".git",
    ".hg",
    ".svn",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "composer.json",
}


def find_collection_root(target: Path) -> Path:
    """Walk up from ``target`` to the nearest project root.

    Collecting from here (rather than just the target's own folder) is what lets
    a directory exclude callers that live outside it: they get parsed, found to
    be out of scope, and pruned. Falls back to the target's own directory when no
    project marker is found, preserving the original single-folder behaviour.
    """
    base = target if target.is_dir() else target.parent
    for cand in (base, *base.parents):
        if any((cand / m).exists() for m in PROJECT_MARKERS):
            return cand
    return base


def collect_files(path: Path) -> list[Path]:
    if path.is_file():
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            return [path]
        sys.exit(
            f"Error: unsupported file type '{path.suffix}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    files: list[Path] = []
    for f in path.rglob("*"):
        if f.is_symlink():
            continue
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS:
            # Skip ignored directories. Only inspect path segments *below* the
            # target root — otherwise an ancestor dir that happens to be named
            # "build", "env", "target", etc. would wrongly exclude everything.
            if any(part in IGNORE_DIRS for part in f.relative_to(path).parts):
                continue
            files.append(f)
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(
        description="Generate an interactive call-graph HTML from source code.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("path", help="Source file or directory to analyze")
    parser.add_argument(
        "-o", "--output", default="graph.html", help="Output HTML file (default: graph.html)"
    )
    parser.add_argument(
        "--no-possible", action="store_true", help="Exclude low-confidence (ambiguous) call edges"
    )
    parser.add_argument(
        "--no-external",
        action="store_true",
        help="Exclude external/stdlib/builtin calls (only show in-project functions)",
    )
    args = parser.parse_args()

    target = Path(args.path).resolve()
    if not target.exists():
        sys.exit(f"Error: '{target}' does not exist.")

    print(f"Analyzing: {target}")

    # Collect from the project root (nearest marker walking up), not just the
    # target's own folder. This makes the selected *scope* and the collected set
    # independent: whatever the user points at (file or directory), callers that
    # live elsewhere in the project are parsed so the prune below can exclude
    # them — leaving only the downstream flow out of the scope.
    collect_from = find_collection_root(target)

    # Collect files
    files = collect_files(collect_from)
    if not files:
        sys.exit("Error: no supported source files found.")
    print(f"Found {len(files)} source file(s)")

    # Initialize parsers (lazy, printed once)
    print("Loading parsers…")
    get_registry()  # triggers initialization and prints status

    # Parse
    print("Parsing files…")
    functions = parse_files(files)
    print(f"Extracted {len(functions)} function(s)")

    if not functions:
        sys.exit("Error: no functions found. Check that the source files contain parseable code.")

    # Build graph
    base_dir = str(collect_from)
    graph = build_graph(
        functions,
        base_dir,
        include_possible=not args.no_possible,
        include_external=not args.no_external,
    )

    # ── Flow scoping ────────────────────────────────────────────────────────
    # The *scope* is the set of files the user pointed at: the single entry file,
    # or every collected file located under the target directory. We prune the
    # graph to only what is reachable *from* the scope via outgoing (call) edges,
    # dropping callers that live outside it — e.g. test files that call into the
    # scope. What remains is the downstream flow, not the full bidirectional call
    # graph. Because collection reaches the whole project (see find_collection_root),
    # those outside callers were parsed and so can actually be excluded here, for a
    # directory just as for a single file. The entrypoint detection below then
    # reveals where each remaining flow starts.
    scope_files = (
        {str(target)} if target.is_file() else {str(f) for f in files if target in f.parents}
    )

    seed_ids: set[str] = {n.id for n in graph.nodes if n.file in scope_files}

    outgoing: dict[str, list[str]] = {}
    for e in graph.edges:
        outgoing.setdefault(e.source, []).append(e.target)

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

    # Mark entrypoints (flow roots) and per-node depth on the pruned graph.
    compute_flow_metadata(graph, seed_ids & reachable)
    entrypoint_count = sum(1 for n in graph.nodes if n.is_entrypoint)
    print(f"Identified {entrypoint_count} flow entrypoint(s)")

    definite = sum(1 for e in graph.edges if e.confidence == "definite")
    possible = sum(1 for e in graph.edges if e.confidence == "possible")
    external = sum(1 for e in graph.edges if e.confidence == "external")
    ext_nodes = sum(1 for n in graph.nodes if n.language == "external")
    print(
        f"Resolved {definite} definite edge(s), {possible} possible edge(s), "
        f"{external} external edge(s) to {ext_nodes} external node(s)"
    )

    # Render HTML
    title = target.name
    print("Rendering HTML…")
    html = render(graph, title)

    # Write output
    out = Path(args.output)
    out.write_text(html, encoding="utf-8")
    size_kb = out.stat().st_size / 1024
    print(f"\n✓ Call graph written to: {out}  ({size_kb:.0f} KB)")
    print(f"  {len(graph.nodes)} nodes, {len(graph.edges)} edges")


if __name__ == "__main__":
    main()
