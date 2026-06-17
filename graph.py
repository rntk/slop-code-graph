#!/usr/bin/env python3
"""
Call Graph Generator
Usage:
  python graph.py <file_or_directory> -o graph.html
  python graph.py src/main.py -o out.html
  python graph.py ./my_project -o out.html
  python graph.py ./my_project -o out.html --llm-api-url http://localhost:8080

When LLM file summaries are generated, the HTML output includes a "Summary only"
toolbar toggle that collapses each summarized file to a single node showing its
description while preserving cross-file call edges.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from src.graph_builder import CallGraph, build_graph, compute_flow_metadata, is_test_path
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


def _build_file_summaries(graph: CallGraph, llm, cache_dir: Path | None = None) -> dict[str, str]:
    """Group nodes by file, concat bodies of flow-used functions, ask LLM for brief file summary.

    The summaries describe the *role of the file* within the pruned downstream flow.
    Keys are the relative_file strings used for visual grouping.
    """
    import hashlib
    import json
    from collections import defaultdict

    by_file: dict[str, list] = defaultdict(list)
    for n in graph.nodes:
        if getattr(n, "language", None) == "external":
            continue
        key = getattr(n, "relative_file", None) or getattr(n, "file", None)
        if not key:
            continue
        by_file[key].append(n)

    system_prompt = (
        "You are a senior engineer. The user will give you the concatenated source "
        "bodies of several functions that all live in ONE source file and participate "
        "in a call graph flow. Write a very brief (1-3 sentences) description of what "
        "this file does / contributes in the context of the flow. Focus on purpose and "
        "high-level responsibility. Be terse. Output plain text only, no labels or markdown."
    )

    cache: dict[str, str] = {}
    cache_file = None
    if cache_dir:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = cache_dir / "graph_llm_cache.json"
            if cache_file.exists():
                with open(cache_file, encoding="utf-8") as f:
                    cache = json.load(f)
        except Exception as e:
            print(f"  Warning: failed to load LLM cache: {e}")

    summaries: dict[str, str] = {}
    budget = 9200  # characters of source to stay well under context
    for rel in sorted(by_file.keys()):
        nodes = by_file[rel]
        # Order for readability: shallower depth first, then source order inside file
        nodes_sorted = sorted(
            nodes,
            key=lambda n: (getattr(n, "depth", 0), getattr(n, "start_line", 0)),
        )

        parts: list[str] = []
        used = 0
        for n in nodes_sorted:
            qn = getattr(n, "qualified_name", getattr(n, "name", "fn"))
            hdr = f"\n### {qn} (L{getattr(n, 'start_line', 0)}-{getattr(n, 'end_line', 0)})\n"
            body = getattr(n, "source_code", "") or ""
            chunk = hdr + body
            if used + len(chunk) > budget and parts:
                break
            parts.append(chunk)
            used += len(chunk)
        snippet = "".join(parts).strip()
        if not snippet:
            continue

        # Start the user prompt with a stable instruction prefix so all
        # per-file summary requests share the same leading tokens after the
        # (also stable) system prompt. This improves KV/prefix cache hit rate.
        user_prompt = (
            "Brief summary of this file's role in the flow:\n\n"
            f"FILE: {rel}\n\n"
            f"Functions from this file that appear in the flow:\n{snippet}"
        )

        # Generate a stable hash-based key for the cache using both prompts
        prompt_key = hashlib.sha256(
            (system_prompt + "\n" + user_prompt).encode("utf-8")
        ).hexdigest()

        if prompt_key in cache:
            summaries[rel] = cache[prompt_key]
            continue

        try:
            resp = llm.complete(
                user_prompt=user_prompt, system_prompt=system_prompt, temperature=0.1
            )
            text = (resp.content or "").strip()
            if text:
                # keep reasonably short for UI tooltip
                summary_text = text[:600]
                summaries[rel] = summary_text
                if cache_file is not None:
                    cache[prompt_key] = summary_text
                    try:
                        with open(cache_file, "w", encoding="utf-8") as f:
                            json.dump(cache, f, ensure_ascii=False, indent=2)
                    except Exception as e:
                        print(f"  Warning: failed to write LLM cache: {e}")
        except Exception:
            # per-file resilience; continue with other files
            continue

    return summaries


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
    parser.add_argument(
        "--llm-api-url",
        default=os.environ.get("LLM_API_URL"),
        help="Base URL of an OpenAI-compatible LLM API (e.g. http://host:port) for file-level flow summaries. Also reads LLM_API_URL env var. When provided, per-file summaries are generated from concatenated function bodies and attached to file groups in the graph.",
    )
    parser.add_argument(
        "--canvas",
        action="store_true",
        help="Also build the Canvas view: glue the flow's function bodies into one "
        "document, split it into topical sections via the LLM (topic-ranges), and "
        "generate a terse summary per topic. Requires --llm-api-url / LLM_API_URL.",
    )
    args = parser.parse_args()

    if args.canvas and not args.llm_api_url:
        sys.exit(
            "Error: --canvas requires an LLM. Pass --llm-api-url or set LLM_API_URL."
        )

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
    if target.is_file():
        scope_files = {str(target)}
    else:
        scope_files = {str(f) for f in files if target in f.parents}
        # Production and test code are different flows. When the user points at a
        # directory we seed the *production* flow only — test files that happen to
        # live under it would otherwise each become their own entrypoint and mix
        # test diagrams into the production one. A user who wants a test flow can
        # point directly at the test file/dir (handled by the fallback below, and
        # by the single-file branch above). If the scope is *entirely* tests
        # (e.g. the target is a tests/ directory), keep them — that is clearly
        # what was asked for.
        production = {p for p in scope_files if not is_test_path(p)}
        if production:
            scope_files = production

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

    # ── Optional LLM file-level summaries ───────────────────────────────────
    # When --llm-api-url (or LLM_API_URL) is provided we use the LlamaCPP
    # client to produce a brief description for each file that contributes
    # functions to the (pruned) flow. We concatenate the bodies of the
    # functions from that file (ordered by depth then source order) and ask
    # for a terse high-level summary of the file's role in the flow. These
    # summaries are attached under file keys so the frontend can show them
    # as hover/click tooltips over the visual file-group containers.
    file_summaries: dict[str, str] = {}
    canvas_data: dict | None = None
    llm_url = args.llm_api_url
    if llm_url:
        from llm.llamacpp import LLamaCPP

        cache_dir = collect_from / ".traverse-cache"
        llm_client = LLamaCPP(host=llm_url, temperature=0.1, max_retries=2)

        print("Requesting LLM file summaries…")
        try:
            file_summaries = _build_file_summaries(graph, llm_client, cache_dir=cache_dir)
            filled = sum(1 for v in file_summaries.values() if v)
            print(f"  LLM summaries generated for {filled} file(s)")
        except Exception as e:
            print(f"  Warning: LLM file summary generation skipped: {e}")

        # ── Optional Canvas view ────────────────────────────────────────────
        # Glue the flow's function bodies into one document, ask the LLM to
        # partition it into topical sections (topic-ranges), and summarize each.
        if args.canvas:
            print("Building Canvas view (topic split + summaries)…")
            try:
                from src.canvas import build_canvas_data

                canvas_data = build_canvas_data(
                    graph,
                    llm_client,
                    cache_dir=cache_dir,
                    file_summaries=file_summaries,
                )
                if canvas_data:
                    print(
                        f"  Canvas: {canvas_data['stats']['topicCount']} topic(s) "
                        f"over {canvas_data['stats']['lineCount']} line(s)"
                    )
                else:
                    print("  Canvas: no summarizable flow source; view skipped")
            except Exception as e:
                print(f"  Warning: Canvas view generation skipped: {e}")

    # Render HTML
    title = target.name
    print("Rendering HTML…")
    html = render(graph, title, file_summaries=file_summaries, canvas=canvas_data)

    # Write output
    out = Path(args.output)
    out.write_text(html, encoding="utf-8")
    size_kb = out.stat().st_size / 1024
    print(f"\n✓ Call graph written to: {out}  ({size_kb:.0f} KB)")
    print(f"  {len(graph.nodes)} nodes, {len(graph.edges)} edges")


if __name__ == "__main__":
    main()
