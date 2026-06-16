import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fetchFlowSummary } from '../api';
import type { GraphNode, GraphResponse } from '../types';
import { LoadingSpinner } from './LoadingSpinner';

interface FlowExplorerProps {
  graph: GraphResponse | null;
  loadingGraph: boolean;
  graphError: string | null;
}

function isExternalNode(node: GraphNode): boolean {
  return (
    node.stable_key.startsWith('external::') ||
    !node.source_code ||
    node.relative_file === ''
  );
}

function formatNodeLabel(node: GraphNode): string {
  if (node.class_name) {
    return `${node.class_name}.${node.name}`;
  }
  return node.qualified_name || node.name;
}

function formatLocation(node: GraphNode): string {
  if (isExternalNode(node)) {
    return 'external';
  }
  return `${node.relative_file}:${node.start_line}-${node.end_line}`;
}

export function FlowExplorer({
  graph,
  loadingGraph,
  graphError,
}: FlowExplorerProps) {
  const [currentNodeId, setCurrentNodeId] = useState<string | null>(null);
  const [summary, setSummary] = useState('');
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);

  // Per-entrypoint summaries fetched lazily so they can be shown in the initial list view.
  const [epSummaries, setEpSummaries] = useState<Record<string, { summary: string; truncated: boolean }>>({});
  // Track which entrypoints we've already initiated a background summary fetch for (per graph).
  const fetchedEpRef = useRef<Set<string>>(new Set());

  const nodeMap = useMemo(() => {
    const map = new Map<string, GraphNode>();
    graph?.nodes.forEach((node) => map.set(node.id, node));
    return map;
  }, [graph]);

  const entrypointNodes = useMemo(() => {
    if (!graph) return [];
    return graph.entrypoints
      .map((id) => nodeMap.get(id))
      .filter((n): n is GraphNode => n !== undefined);
  }, [graph, nodeMap]);

  const currentNode = currentNodeId ? nodeMap.get(currentNodeId) ?? null : null;

  const directCallees = useMemo(() => {
    if (!graph || !currentNodeId) return [];
    const targets = graph.edges
      .filter((e) => e.source === currentNodeId)
      .map((e) => nodeMap.get(e.target))
      .filter((n): n is GraphNode => n !== undefined);
    return targets.sort((a, b) => formatNodeLabel(a).localeCompare(formatNodeLabel(b)));
  }, [graph, currentNodeId, nodeMap]);

  const resetFlowState = useCallback(() => {
    setCurrentNodeId(null);
    setSummary('');
    setSummaryError(null);
    setTruncated(false);
  }, []);

  useEffect(() => {
    resetFlowState();
    setEpSummaries({});
    fetchedEpRef.current = new Set();
  }, [graph, resetFlowState]);

  // Lazily fetch (and cache) very brief summaries for entrypoints so the initial
  // view can surface them per the spec. Non-blocking; failures are ignored.
  useEffect(() => {
    if (!graph || entrypointNodes.length === 0) return;
    entrypointNodes.forEach((node) => {
      if (fetchedEpRef.current.has(node.id)) return;
      if (epSummaries[node.id]) return;
      if (isExternalNode(node)) return;
      fetchedEpRef.current.add(node.id);
      fetchFlowSummary({
        scope_file: graph.scope_file,
        start_node_id: node.id,
      })
        .then((res) => {
          setEpSummaries((prev) => ({
            ...prev,
            [node.id]: { summary: res.summary, truncated: res.truncated },
          }));
        })
        .catch(() => {
          // Background summary fetch failed (e.g. no LLM); user can still use Explore.
          // Allow a future retry by removing from the ref on failure? Keep it to avoid storms;
          // a manual Explore will still work and will populate via loadSummary path.
        });
    });
  }, [graph, entrypointNodes]);

  const loadSummary = useCallback(
    async (nodeId: string, existingSummary?: string, forceRegenerate?: boolean) => {
      if (!graph) return;

      const node = nodeMap.get(nodeId);
      if (!node) return;

      if (existingSummary && !forceRegenerate) {
        setSummary(existingSummary);
        setSummaryError(null);
        setTruncated(false);
        return;
      }

      if (isExternalNode(node)) {
        setSummary(
          `External call "${node.name}" — no source body available. This node represents a library or builtin dependency.`,
        );
        setSummaryError(null);
        setTruncated(false);
        return;
      }

      setSummaryLoading(true);
      setSummaryError(null);
      try {
        const result = await fetchFlowSummary({
          scope_file: graph.scope_file,
          start_node_id: nodeId,
          regenerate: !!forceRegenerate,
        });
        setSummary(result.summary);
        setTruncated(result.truncated);
        // Keep entrypoint list summaries in sync when exploring from the list or re-centering.
        if (graph.entrypoints.includes(nodeId)) {
          setEpSummaries((prev) => ({
            ...prev,
            [nodeId]: { summary: result.summary, truncated: result.truncated },
          }));
        }
      } catch (err) {
        setSummary('');
        setSummaryError(
          err instanceof Error ? err.message : 'Failed to generate summary',
        );
      } finally {
        setSummaryLoading(false);
      }
    },
    [graph, nodeMap],
  );

  const exploreNode = useCallback(
    async (nodeId: string) => {
      setCurrentNodeId(nodeId);
      const node = nodeMap.get(nodeId);
      const pre = epSummaries[nodeId];
      if (pre) {
        // Seed the detailed view from the already-fetched entrypoint summary (no extra LLM call).
        setSummary(pre.summary);
        setSummaryError(null);
        setTruncated(pre.truncated);
        // Still call loadSummary with existing so it short-circuits and doesn't re-fetch.
        await loadSummary(nodeId, pre.summary);
        return;
      }
      await loadSummary(nodeId, node?.summary || undefined);
    },
    [loadSummary, nodeMap, epSummaries],
  );

  if (loadingGraph) {
    return (
      <section className="flow-explorer panel">
        <div className="flow-explorer__placeholder">
          <LoadingSpinner label="Building call graph…" />
        </div>
      </section>
    );
  }

  if (graphError) {
    return (
      <section className="flow-explorer panel">
        <div className="flow-explorer__placeholder">
          <p className="error-text">{graphError}</p>
        </div>
      </section>
    );
  }

  if (!graph) {
    return (
      <section className="flow-explorer panel">
        <div className="flow-explorer__placeholder">
          <p className="muted-text">Select a file to explore its call flow.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="flow-explorer panel">
      <header className="panel__header">
        <div>
          <h2>Flow Explorer</h2>
          <p className="panel__subtitle">{graph.scope_file}</p>
        </div>
        <div className="stats-badge">
          {graph.stats.nodes} nodes · {graph.stats.edges} edges
        </div>
      </header>

      <div className="flow-explorer__content">
        <div className="flow-explorer__main">
          {!currentNode && (
            <section className="entrypoints">
              <h3>Entrypoints</h3>
              <p className="muted-text">
                Functions at the root of this file&apos;s call graph.
              </p>
              <ul className="node-list">
                {entrypointNodes.map((node) => (
                  <li key={node.id} className="node-card">
                    <div className="node-card__header">
                      <div>
                        <span className="badge badge--entry">entrypoint</span>
                        <strong className="node-card__name">
                          {formatNodeLabel(node)}
                        </strong>
                        <span className="node-card__location">
                          {formatLocation(node)}
                        </span>
                      </div>
                      <button
                        type="button"
                        className="btn btn--primary"
                        onClick={() => void exploreNode(node.id)}
                      >
                        Explore this flow
                      </button>
                    </div>
                    {epSummaries[node.id]?.summary ? (
                      <p className="node-card__summary">
                        {epSummaries[node.id].summary}
                        {epSummaries[node.id].truncated ? ' …' : ''}
                      </p>
                    ) : node.summary ? (
                      <p className="node-card__summary">{node.summary}</p>
                    ) : null}
                  </li>
                ))}
                {entrypointNodes.length === 0 && (
                  <li className="muted-text">No entrypoints found in this scope.</li>
                )}
              </ul>
            </section>
          )}

          {currentNode && (
            <section className="current-flow">
              <div className="current-flow__header">
                <div>
                  <p className="current-flow__label">Flow starting from here</p>
                  <h3 className="current-flow__title">
                    {formatNodeLabel(currentNode)}
                  </h3>
                  <p className="node-card__location">{formatLocation(currentNode)}</p>
                </div>
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={resetFlowState}
                >
                  ← Back to entrypoints
                </button>
              </div>

              <div className="summary-panel">
                {summaryLoading && (
                  <LoadingSpinner label="Generating flow summary…" size="sm" />
                )}
                {!summaryLoading && summaryError && (
                  <p className="error-text">{summaryError}</p>
                )}
                {!summaryLoading && !summaryError && summary && (
                  <>
                    <p className="summary-panel__text">{summary}</p>
                    {truncated && (
                      <p className="summary-panel__note">
                        Summary was truncated due to context limits.
                      </p>
                    )}
                    <div style={{ marginTop: '0.5rem' }}>
                      <button
                        type="button"
                        className="btn btn--ghost"
                        onClick={() => {
                          if (currentNodeId) void loadSummary(currentNodeId, undefined, true);
                        }}
                        title="Re-run the LLM for a fresh summary (bypasses cache)"
                      >
                        Regenerate
                      </button>
                    </div>
                  </>
                )}
                {!summaryLoading && !summaryError && !summary && (
                  <div className="summary-panel__empty">
                    <p className="muted-text">No summary yet for this flow.</p>
                    <button
                      type="button"
                      className="btn btn--primary"
                      onClick={() => void loadSummary(currentNode.id)}
                    >
                      Generate summary
                    </button>
                  </div>
                )}
              </div>

              <section className="next-steps">
                <h4>Next steps</h4>
                <p className="muted-text">
                  Direct callees from the current position. Selecting one re-centers the
                  flow.
                </p>
                {directCallees.length === 0 ? (
                  <p className="muted-text">No outgoing calls from this node.</p>
                ) : (
                  <ul className="callee-list">
                    {directCallees.map((callee) => {
                      const external = isExternalNode(callee);
                      return (
                        <li key={callee.id}>
                          <button
                            type="button"
                            className={`callee-list__item${currentNodeId === callee.id ? ' callee-list__item--active' : ''}`}
                            onClick={() => void exploreNode(callee.id)}
                          >
                            <span className="callee-list__name">
                              {formatNodeLabel(callee)}
                            </span>
                            <span className="callee-list__meta">
                              {external ? 'external' : formatLocation(callee)}
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>
            </section>
          )}
        </div>

        <aside className="source-panel">
          <h3>Source</h3>
          {currentNode ? (
            isExternalNode(currentNode) ? (
              <p className="muted-text">
                No source code available for external node &ldquo;{currentNode.name}
                &rdquo;.
              </p>
            ) : (
              <pre className="source-code">
                <code>{currentNode.source_code}</code>
              </pre>
            )
          ) : (
            <p className="muted-text">
              Select an entrypoint or callee to inspect source code.
            </p>
          )}
        </aside>
      </div>
    </section>
  );
}