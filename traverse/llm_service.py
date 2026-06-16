"""Position-dependent flow summaries via LLM."""

from __future__ import annotations

import logging
from collections import deque
from pathlib import Path

from llm.base import LLMClient
from src.graph_builder import CallGraph, GraphNode
from traverse.cache import SummaryCache
from traverse.config import TraverseConfig
from traverse.graph_service import ScopedGraph

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a senior engineer. Given a call subgraph and the full source of each "
    "function in it, produce a very brief, high-level description (1-3 sentences) of "
    "the flow starting at the given entry point in this specific context. Focus on "
    "purpose and shape, not implementation minutiae. Be terse. Plain text only."
)

# Fixed prefix for edge-label requests so that the instruction tokens are stable
# across calls (aids KV cache / prefix cache reuse on the LLM backend).
EDGE_LABEL_SYSTEM_PROMPT = (
    "You are a senior engineer. For each callee, reply with exactly one line in the form "
    "'QUALIFIED_NAME: 3-6 word phrase' describing what the call from the origin to that "
    "callee does in this specific flow. Be terse and specific. No extra text."
)


def _outgoing_map(graph: CallGraph) -> dict[str, list[str]]:
    outgoing: dict[str, list[str]] = {}
    for edge in graph.edges:
        outgoing.setdefault(edge.source, []).append(edge.target)
    return outgoing


def reachable_from(graph: CallGraph, start_id: str) -> set[str]:
    outgoing = _outgoing_map(graph)
    seen: set[str] = set()
    queue: deque[str] = deque([start_id])
    while queue:
        nid = queue.popleft()
        if nid in seen:
            continue
        seen.add(nid)
        for tid in outgoing.get(nid, []):
            if tid not in seen:
                queue.append(tid)
    return seen


def _collect_bodies(
    graph: CallGraph,
    start_id: str,
    reachable_ids: set[str],
    *,
    char_budget: int,
) -> tuple[list[GraphNode], bool]:
    """BFS from the chosen start node (within reachable), preferring direct callees; stop at char budget."""
    node_by_id = {n.id: n for n in graph.nodes}
    if start_id not in node_by_id:
        return [], False

    outgoing = _outgoing_map(graph)

    # BFS from start_id, only traversing nodes inside the reachable slice.
    # Siblings at each layer are sorted by (relative_file, name) for determinism.
    order: list[str] = []
    seen: set[str] = set()
    from collections import deque

    q: deque[str] = deque([start_id])
    seen.add(start_id)
    while q:
        nid = q.popleft()
        if nid in reachable_ids:
            order.append(nid)
        children = [
            tid
            for tid in outgoing.get(nid, [])
            if tid in reachable_ids and tid not in seen
        ]
        # Stable order within layer: by file then name
        children.sort(key=lambda tid: (node_by_id.get(tid).relative_file if tid in node_by_id else "", node_by_id.get(tid).name if tid in node_by_id else ""))
        for tid in children:
            seen.add(tid)
            q.append(tid)

    selected: list[GraphNode] = []
    used = 0
    truncated = False
    for nid in order:
        node = node_by_id.get(nid)
        if node is None:
            continue
        body = node.source_code or ""
        cost = len(body) + 200
        if used + cost > char_budget and selected:
            truncated = True
            break
        if used + cost > char_budget and not selected:
            # Include at least one node, truncated
            node = _truncate_node(node, char_budget - used)
            selected.append(node)
            truncated = True
            break
        selected.append(node)
        used += cost
    return selected, truncated


def _truncate_node(node: GraphNode, max_chars: int) -> GraphNode:
    from dataclasses import replace

    if max_chars <= 0 or not node.source_code:
        return node
    code = node.source_code
    if len(code) <= max_chars:
        return node
    truncated_code = code[: max(0, max_chars - 40)] + "\n# ... [truncated] ..."
    return replace(node, source_code=truncated_code)


def _file_mtimes(nodes: list[GraphNode]) -> dict[str, float]:
    mtimes: dict[str, float] = {}
    for node in nodes:
        if not node.file:
            continue
        path = Path(node.file)
        if path.exists():
            mtimes[node.relative_file] = path.stat().st_mtime
    return mtimes


def _build_user_prompt(
    start: GraphNode,
    graph: CallGraph,
    reachable_ids: set[str],
    bodies: list[GraphNode],
    truncated: bool,
) -> str:
    lines: list[str] = []
    # Put fixed instructional text first so that the token prefix is identical
    # for all flow-summary requests (enables KV/prefix cache reuse on backends
    # that support cache_prompt or equivalent).
    lines.append("Describe the flow starting at the entry point below. Focus on purpose and shape.")
    lines.append("")
    lines.append("Entry point:")
    lines.append(
        f"  {start.qualified_name} in {start.relative_file} "
        f"(lines {start.start_line}-{start.end_line})"
    )
    lines.append("")
    lines.append("Subgraph edges (caller -> callee) within the view:")
    body_ids = {n.id for n in bodies}
    for edge in graph.edges:
        if edge.source in body_ids and edge.target in body_ids:
            src = next((n for n in graph.nodes if n.id == edge.source), None)
            tgt = next((n for n in graph.nodes if n.id == edge.target), None)
            if src and tgt:
                lines.append(f"  {src.qualified_name} -> {tgt.qualified_name} ({edge.confidence})")
    lines.append("")
    if truncated:
        lines.append("Note: some downstream function bodies were omitted due to size budget.")
        lines.append("")
    lines.append("Source of functions in the flow (roughly in call order):")
    lines.append("")
    for node in bodies:
        cls = f"{node.class_name}." if node.class_name else ""
        lines.append(
            f"=== FILE: {node.relative_file}  FN: {cls}{node.name} "
            f"(L{node.start_line}-{node.end_line}) ==="
        )
        if node.source_code:
            lines.append(node.source_code)
        else:
            lines.append("<no source — external/stdlib>")
        lines.append("")
    return "\n".join(lines)


def external_summary(node: GraphNode) -> str:
    return f"Calls into {node.name} (external/stdlib/third-party)."


class FlowSummaryService:
    def __init__(
        self,
        config: TraverseConfig,
        cache: SummaryCache,
        llm: LLMClient | None = None,
    ) -> None:
        self._config = config
        self._cache = cache
        self._llm = llm

    def summarize(
        self,
        scoped: ScopedGraph,
        start_node_id: str,
        *,
        bypass_cache: bool = False,
    ) -> dict:
        node = scoped.node_by_id.get(start_node_id)
        if node is None:
            raise KeyError(f"node not found: {start_node_id}")

        if node.language == "external" or not node.source_code:
            reachable = reachable_from(scoped.graph, start_node_id)
            return {
                "start_node_id": start_node_id,
                "summary": external_summary(node),
                "edge_labels": {},
                "nodes_in_view": sorted(reachable),
                "truncated": False,
            }

        reachable = reachable_from(scoped.graph, start_node_id)
        bodies, truncated = _collect_bodies(
            scoped.graph,
            start_node_id,
            reachable,
            char_budget=self._config.prompt_char_budget,
        )
        mtimes = _file_mtimes(bodies)
        cache_key = self._cache.make_key(
            scope_file=scoped.scope_file,
            start_stable_key=node.stable_key,
            reachable_signature=SummaryCache.reachable_signature(list(reachable)),
            mtimes_signature=SummaryCache.mtimes_signature(mtimes),
        )

        if not bypass_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        if self._llm is None:
            raise RuntimeError("LLM client not configured")

        user_prompt = _build_user_prompt(node, scoped.graph, reachable, bodies, truncated)
        logger.info("LLM raw prompt (system):\n%s", SYSTEM_PROMPT)
        logger.info("LLM raw prompt (user):\n%s", user_prompt)
        response = self._llm.complete(
            user_prompt=user_prompt,
            system_prompt=SYSTEM_PROMPT,
            temperature=0.1,
        )
        logger.info("LLM raw response:\n%s", response.content)
        summary = (response.content or "").strip()
        if not summary:
            raise RuntimeError("LLM returned empty summary")

        edge_labels = _edge_labels_for_immediate(node, scoped.graph, self._llm)

        result = {
            "start_node_id": start_node_id,
            "summary": summary,
            "edge_labels": edge_labels,
            "nodes_in_view": sorted(reachable),
            "truncated": truncated,
        }
        self._cache.set(cache_key, result)
        return result


def _edge_labels_for_immediate(
    start: GraphNode,
    graph: CallGraph,
    llm: LLMClient,
) -> dict[str, str]:
    """Optional short labels for immediate outgoing edges (batched in one LLM call)."""
    immediate = [e for e in graph.edges if e.source == start.id]
    if not immediate:
        return {}
    # Build a small list of targets (cap to keep prompt tiny)
    targets: list[GraphNode] = []
    for e in immediate[:12]:
        t = next((n for n in graph.nodes if n.id == e.target), None)
        if t is not None:
            targets.append(t)
    if not targets:
        return {}

    # Use a dedicated stable system prompt (instructions) and put variable data
    # (origin + callees) in the user prompt. This gives a long fixed prefix for
    # KV cache reuse on all edge-label requests.
    lines: list[str] = []
    lines.append(f"Origin: {start.qualified_name}")
    lines.append("Callees:")
    for t in targets:
        lines.append(f"- {t.qualified_name}")
    user_prompt = "\n".join(lines)

    try:
        logger.info("LLM raw prompt (system):\n%s", EDGE_LABEL_SYSTEM_PROMPT)
        logger.info("LLM raw prompt (user):\n%s", user_prompt)
        resp = llm.complete(user_prompt=user_prompt, system_prompt=EDGE_LABEL_SYSTEM_PROMPT, temperature=0.0)
        logger.info("LLM raw response:\n%s", resp.content)
        content = (resp.content or "").strip()
        qname_to_edge_id: dict[str, str] = {}
        for t in targets:
            e = next((ee for ee in immediate if ee.target == t.id), None)
            if e:
                qname_to_edge_id[t.qualified_name] = e.id

        labels: dict[str, str] = {}
        for raw in content.splitlines():
            if ":" not in raw:
                continue
            left, right = raw.split(":", 1)
            name = left.strip()
            label = right.strip().strip('"').strip("'")
            if not name or not label:
                continue
            eid = qname_to_edge_id.get(name)
            if eid:
                labels[eid] = label
        return labels
    except Exception:
        logger.debug("batch edge label generation failed for start=%s", start.id, exc_info=True)
        return {}
