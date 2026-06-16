"""Main call-graph application script (built on GraphView).

Injected verbatim into the generated HTML via the @@APP@@ placeholder.
"""

APP_SCRIPT = r"""
// ── Data ──────────────────────────────────────────────────────────────────
const GRAPH_DATA = @@GRAPHDATA@@;

// ── Graph engine init ───────────────────────────────────────────────────────
const gv = new GraphView(document.getElementById('cy'), {
  nodes: GRAPH_DATA.nodes,
  edges: GRAPH_DATA.edges,
  nodeClasses: (n) => n.language + (n.language === 'external' ? ' external' : '') + (n.is_entrypoint ? ' entrypoint' : ''),
  shapeOf: (n) => (n.language === 'external' ? 'round-tag' : 'round-rectangle'),
  // Group function nodes into file containers in the hierarchical layout.
  // External (stdlib/builtin) nodes are deduped across files, so they belong to
  // no single file and stay ungrouped (null).
  groupOf: (n) => (n.language === 'external' ? null : (n.relative_file || n.file || null)),
  labelOf: (n) => (n.class_name ? n.class_name + '.' + n.name : n.name),
  fillOf: (n) => n.color,
  edgeClasses: (e) => e.confidence,
  onNodeTap: (data) => showPanel(data),
  onBgTap: () => closePanel(),
});

// ── Layout ────────────────────────────────────────────────────────────────
function applyLayout(name) {
  if (name === 'dagre-lr') gv.layout('dagre', { rankDir: 'LR', nodeSep: 32, rankSep: 120 });
  else if (name === 'dagre-tb') gv.layout('dagre', { rankDir: 'TB', nodeSep: 32, rankSep: 90 });
  else if (name === 'cose') gv.layout('cose');
  else if (name === 'concentric') gv.layout('concentric');
}
applyLayout('dagre-lr');

// ── Callers / Callees index ───────────────────────────────────────────────
const calleeMap = {};
const callerMap = {};
const nodeById = {};
GRAPH_DATA.nodes.forEach((n) => { calleeMap[n.id] = []; callerMap[n.id] = []; nodeById[n.id] = n; });
GRAPH_DATA.edges.forEach((e) => {
  if (calleeMap[e.source]) calleeMap[e.source].push(e.target);
  if (callerMap[e.target]) callerMap[e.target].push(e.source);
});

// ── Info panel ────────────────────────────────────────────────────────────
const panel = document.getElementById('panel');
const panelTitle = document.getElementById('panel-title');
const panelMeta = document.getElementById('panel-meta');
const sourceCode = document.getElementById('source-code');
const calleesSection = document.getElementById('callees-section');
const callersSection = document.getElementById('callers-section');
let currentData = null;

function updateFlowBtn() {
  const ok = currentData && currentData.language !== 'external'
    && Array.isArray(currentData.flow) && currentData.flow.length;
  document.getElementById('btn-flow').style.display = ok ? 'block' : 'none';
}

function showPanel(data) {
  currentData = data;
  panel.classList.add('open');
  panelTitle.textContent = data.qualified_name || data.name;
  panelTitle.title = data.qualified_name || data.name;

  const isExternal = data.language === 'external';
  const badge = `<span class="lang-badge" style="background:${data.color}">${data.language}</span>`;
  const file = data.relative_file || data.file;
  const lines = `L${data.start_line}–${data.end_line}`;

  panelMeta.innerHTML = isExternal
    ? `
    <div class="info-row"><span class="info-label">Lang</span><span class="info-val">${badge}</span></div>
    <div class="info-row"><span class="info-label">Kind</span><span class="info-val">External / stdlib / builtin (no definition in this project)</span></div>
  `
    : `
    <div class="info-row"><span class="info-label">Lang</span><span class="info-val">${badge}</span></div>
    <div class="info-row"><span class="info-label">File</span><span class="info-val" title="${data.file}">${file}</span></div>
    <div class="info-row"><span class="info-label">Lines</span><span class="info-val">${lines}</span></div>
    ${data.class_name ? `<div class="info-row"><span class="info-label">Class</span><span class="info-val">${data.class_name}</span></div>` : ''}
    <div class="info-row"><span class="info-label">Flow</span><span class="info-val">${data.is_entrypoint ? '🟢 Entrypoint (flow root)' : 'depth ' + data.depth + ' from entrypoint'}</span></div>
    ${data.summary ? `<div class="info-row"><span class="info-label">Summary</span><span class="info-val">${data.summary}</span></div>` : ''}
  `;

  // External nodes have no source; hide the source block entirely for them.
  document.getElementById('source-wrap').style.display = isExternal ? 'none' : '';
  sourceCode.textContent = data.source_code || '';

  // Callees
  const calleeIds = [...new Set(calleeMap[data.id] || [])];
  calleesSection.innerHTML = calleeIds.length
    ? `<div class="section-title">Calls (${calleeIds.length})</div>` +
      calleeIds.map((tid) => {
        const t = nodeById[tid];
        return t ? `<span class="fn-link" data-id="${tid}" title="${t.relative_file || t.file}: ${t.qualified_name}">${t.qualified_name}</span>` : '';
      }).join('')
    : '';

  // Callers
  const callerIds = [...new Set(callerMap[data.id] || [])];
  callersSection.innerHTML = callerIds.length
    ? `<div class="section-title">Called by (${callerIds.length})</div>` +
      callerIds.map((sid) => {
        const s = nodeById[sid];
        return s ? `<span class="fn-link" data-id="${sid}" title="${s.relative_file || s.file}: ${s.qualified_name}">${s.qualified_name}</span>` : '';
      }).join('')
    : '';

  if (!flowActive) {
    document.getElementById('stat-selection').textContent = `Selected: ${data.qualified_name}`;
  }
  document.getElementById('btn-isolate').style.display =
    (!isExternal && (calleeMap[data.id] || []).length) ? 'block' : 'none';
  updateFlowBtn();
}

document.getElementById('btn-isolate').addEventListener('click', () => {
  if (currentData) isolateFlow(currentData.id);
});

function closePanel() {
  panel.classList.remove('open');
  document.getElementById('stat-selection').textContent = '';
  currentData = null;
  updateFlowBtn();
  gv.unselectAll();
}

document.getElementById('panel-close').addEventListener('click', closePanel);

panel.addEventListener('click', (e) => {
  const link = e.target.closest('.fn-link');
  if (link) {
    const id = link.dataset.id;
    if (nodeById[id]) {
      gv.selectOnly(id);
      gv.center([id], 100);
      showPanel(nodeById[id]);
    }
  }
});

// ── Controls ──────────────────────────────────────────────────────────────
document.getElementById('btn-fit').addEventListener('click', () => gv.fit(40));
document.getElementById('btn-zoom-in').addEventListener('click', () => gv.zoomBy(1.3));
document.getElementById('btn-zoom-out').addEventListener('click', () => gv.zoomBy(1 / 1.3));
document.getElementById('layout-select').addEventListener('change', (e) => applyLayout(e.target.value));

let showPossible = true;
document.getElementById('btn-possible').addEventListener('click', function () {
  showPossible = !showPossible;
  this.classList.toggle('active', showPossible);
  gv.forEachEdge((id, e) => { if (e.confidence === 'possible') gv.showEdge(id, showPossible); });
});

// Toggle external (stdlib/builtin/third-party) nodes and their edges, then
// re-run the current layout so the graph re-flows around what's left.
let showExternal = true;
document.getElementById('btn-external').addEventListener('click', function () {
  showExternal = !showExternal;
  this.classList.toggle('active', showExternal);
  gv.forEachNode((id, n) => { if (n.language === 'external') gv.showNode(id, showExternal); });
  gv.forEachEdge((id, e) => { if (e.confidence === 'external') gv.showEdge(id, showExternal); });
  applyLayout(document.getElementById('layout-select').value);
});

// Toggle file-container grouping, then re-run the current layout. Boxes only
// appear in the hierarchical (dagre) layouts; cose/concentric ignore grouping.
let groupByFile = true;
document.getElementById('btn-group').addEventListener('click', function () {
  groupByFile = !groupByFile;
  this.classList.toggle('active', groupByFile);
  gv.setGrouping(groupByFile);
  applyLayout(document.getElementById('layout-select').value);
});

// ── Flows: entrypoints + downstream isolation ─────────────────────────────
// A "flow" is one entrypoint and everything reachable from it via call edges.
// Isolating a flow dims every node/edge that is not part of that downstream
// subtree, so the user (and, later, an LLM walking the flow) sees a single
// rooted path instead of the whole graph.
const ENTRYPOINTS = GRAPH_DATA.nodes
  .filter((n) => n.is_entrypoint)
  .sort((a, b) => (a.relative_file || '').localeCompare(b.relative_file || '')
    || (a.qualified_name || '').localeCompare(b.qualified_name || ''));

function downstreamOf(rootId) {
  // Transitive closure over callees, including the root. Cycles are handled by
  // the visited set.
  const seen = new Set([rootId]);
  const stack = [rootId];
  while (stack.length) {
    const id = stack.pop();
    (calleeMap[id] || []).forEach((t) => { if (!seen.has(t)) { seen.add(t); stack.push(t); } });
  }
  return seen;
}

let flowActive = false;
function isolateFlow(rootId) {
  const keep = downstreamOf(rootId);
  gv.forEachNode((id) => {
    gv.nodeClass(id, 'dimmed', !keep.has(id));
    gv.nodeClass(id, 'highlighted', false);
  });
  gv.forEachEdge((id, e) => gv.edgeClass(id, 'dimmed', !(keep.has(e.source) && keep.has(e.target))));
  flowActive = true;
  document.getElementById('btn-reset-flow').style.display = '';
  gv.center([...keep], 60);
  const root = nodeById[rootId];
  document.getElementById('stat-selection').textContent =
    `Flow: ${root ? root.qualified_name : rootId} (${keep.size} function${keep.size !== 1 ? 's' : ''})`;
}

function resetFlow() {
  gv.forEachNode((id) => { gv.nodeClass(id, 'dimmed', false); gv.nodeClass(id, 'highlighted', false); });
  gv.forEachEdge((id) => gv.edgeClass(id, 'dimmed', false));
  flowActive = false;
  document.getElementById('btn-reset-flow').style.display = 'none';
  document.getElementById('stat-selection').textContent = '';
}
document.getElementById('btn-reset-flow').addEventListener('click', resetFlow);

// Build the Flows ▾ dropdown from detected entrypoints.
const flowsMenu = document.getElementById('flows-menu');
const flowsBtn = document.getElementById('btn-flows');
flowsMenu.innerHTML = ENTRYPOINTS.length
  ? ENTRYPOINTS.map((n) =>
      `<div class="flow-item" data-id="${n.id}">` +
      `<div class="fi-name">${n.qualified_name}</div>` +
      `<div class="fi-file">${n.relative_file || n.file || ''}</div></div>`
    ).join('')
  : '<div class="fi-empty">No entrypoints detected</div>';
flowsBtn.textContent = `Flows (${ENTRYPOINTS.length}) ▾`;

flowsBtn.addEventListener('click', (e) => { e.stopPropagation(); flowsMenu.classList.toggle('open'); });
flowsMenu.addEventListener('click', (e) => {
  const item = e.target.closest('.flow-item');
  if (!item) return;
  const id = item.dataset.id;
  flowsMenu.classList.remove('open');
  if (nodeById[id]) { gv.selectOnly(id); isolateFlow(id); showPanel(nodeById[id]); }
});
document.addEventListener('click', (e) => {
  if (!e.target.closest('#flows-wrap')) flowsMenu.classList.remove('open');
});

// ── Fuzzy search ──────────────────────────────────────────────────────────
const SEARCH_KEYS = ['name', 'qualified_name', 'relative_file', 'class_name'];
const searchInput = document.getElementById('search');
const searchResults = document.getElementById('search-results');
const searchCount = document.getElementById('search-count');

function clearSearchHighlight() {
  gv.forEachNode((id) => { gv.nodeClass(id, 'dimmed', false); gv.nodeClass(id, 'highlighted', false); });
  gv.forEachEdge((id) => gv.edgeClass(id, 'dimmed', false));
}

searchInput.addEventListener('input', function () {
  const q = this.value.trim();
  if (!q) {
    clearSearchHighlight();
    searchResults.classList.remove('visible');
    searchCount.textContent = '';
    return;
  }

  const results = fuzzySearch(q, GRAPH_DATA.nodes, SEARCH_KEYS, 50);
  const matchIds = new Set(results.map((r) => r.item.id));
  searchCount.textContent = matchIds.size || '';

  gv.forEachNode((id) => {
    const on = matchIds.has(id);
    gv.nodeClass(id, 'highlighted', on);
    gv.nodeClass(id, 'dimmed', !on);
  });
  gv.forEachEdge((id, e) => {
    const both = matchIds.has(e.source) && matchIds.has(e.target);
    gv.edgeClass(id, 'dimmed', !both);
  });

  if (results.length > 0) {
    searchResults.innerHTML = results.slice(0, 20).map((r) => {
      const n = r.item;
      return `<div class="sr-item" data-id="${n.id}">
        <span class="sr-name">${n.qualified_name}</span>
        <span class="sr-file">${n.relative_file || n.file}</span>
      </div>`;
    }).join('');
    searchResults.classList.add('visible');
  } else {
    searchResults.classList.remove('visible');
  }
});

searchResults.addEventListener('click', (e) => {
  const item = e.target.closest('.sr-item');
  if (!item) return;
  const id = item.dataset.id;
  if (nodeById[id]) {
    const focus = [id].concat(calleeMap[id] || [], callerMap[id] || []);
    gv.selectOnly(id);
    gv.center(focus, 80);
    showPanel(nodeById[id]);
  }
  searchResults.classList.remove('visible');
  searchInput.value = '';
  clearSearchHighlight();
  searchCount.textContent = '';
});

document.addEventListener('click', (e) => {
  if (!document.getElementById('search-wrap').contains(e.target)) {
    searchResults.classList.remove('visible');
  }
});

// ── Keyboard shortcuts ────────────────────────────────────────────────────
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closePanel();
    searchInput.value = '';
    clearSearchHighlight();
    searchCount.textContent = '';
    searchResults.classList.remove('visible');
  }
  if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
    e.preventDefault();
    searchInput.focus();
  }
  if (e.key === '0' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    gv.fit(40);
  }
});

// ── Status bar ────────────────────────────────────────────────────────────
const files = new Set(
  GRAPH_DATA.nodes.filter((n) => n.language !== 'external' && n.file).map((n) => n.file)
);
const defCount = GRAPH_DATA.nodes.filter((n) => n.language !== 'external').length;
const extCount = GRAPH_DATA.nodes.length - defCount;
document.getElementById('stat-nodes').textContent =
  `${defCount} function${defCount !== 1 ? 's' : ''}` +
  (extCount ? ` + ${extCount} external` : '');
document.getElementById('stat-edges').textContent =
  `${GRAPH_DATA.edges.length} edge${GRAPH_DATA.edges.length !== 1 ? 's' : ''}`;
document.getElementById('stat-files').textContent =
  `${files.size} file${files.size !== 1 ? 's' : ''}`;
"""
