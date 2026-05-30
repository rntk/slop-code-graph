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


SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".mjs", ".cjs", ".jsx",
    ".ts", ".tsx",
    ".go",
    ".java",
    ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx", ".c++",
    ".php",
}

IGNORE_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".tox", "venv", ".venv",
    "env", ".env", "dist", "build", "target", "vendor",
    ".idea", ".vscode",
}


def collect_files(path: Path) -> list[Path]:
    if path.is_file():
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            return [path]
        sys.exit(f"Error: unsupported file type '{path.suffix}'. "
                 f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")

    files: list[Path] = []
    for f in path.rglob("*"):
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS:
            # Skip ignored directories
            if any(part in IGNORE_DIRS for part in f.parts):
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
        "-o", "--output", default="graph.html",
        help="Output HTML file (default: graph.html)"
    )
    parser.add_argument(
        "--no-possible", action="store_true",
        help="Exclude low-confidence (ambiguous) call edges"
    )
    args = parser.parse_args()

    target = Path(args.path).resolve()
    if not target.exists():
        sys.exit(f"Error: '{target}' does not exist.")

    print(f"Analyzing: {target}")

    # Collect files
    files = collect_files(target)
    if not files:
        sys.exit("Error: no supported source files found.")
    print(f"Found {len(files)} source file(s)")

    # Initialize parsers (lazy, printed once)
    print("Loading parsers…")
    from src.parsers import parse_files, get_registry
    get_registry()  # triggers initialization and prints status

    # Parse
    print("Parsing files…")
    functions = parse_files(files)
    print(f"Extracted {len(functions)} function(s)")

    if not functions:
        sys.exit("Error: no functions found. Check that the source files contain parseable code.")

    # Build graph
    from src.graph_builder import build_graph
    base_dir = str(target) if target.is_dir() else str(target.parent)
    graph = build_graph(functions, base_dir)

    if args.no_possible:
        graph.edges = [e for e in graph.edges if e.confidence == "definite"]

    definite = sum(1 for e in graph.edges if e.confidence == "definite")
    possible = sum(1 for e in graph.edges if e.confidence == "possible")
    print(f"Resolved {definite} definite edge(s), {possible} possible edge(s)")

    # Render HTML
    from src.renderer import render
    title = target.name
    print("Rendering HTML (may download JS libraries on first run)…")
    html = render(graph, title)

    # Write output
    out = Path(args.output)
    out.write_text(html, encoding="utf-8")
    size_kb = out.stat().st_size / 1024
    print(f"\n✓ Call graph written to: {out}  ({size_kb:.0f} KB)")
    print(f"  {len(graph.nodes)} nodes, {len(graph.edges)} edges")


if __name__ == "__main__":
    main()
