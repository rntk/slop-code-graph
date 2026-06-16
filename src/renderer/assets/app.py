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
  // Group function nodes into file containers in graph layouts.
  // External (stdlib/builtin) nodes are deduped across files, so they belong to
  // no single file and stay ungrouped (null).
  groupOf: (n) => (n.language === 'external' ? null : (n.relative_file || n.file || null)),
  labelOf: (n) => (n.class_name ? n.class_name + '.' + n.name : n.name),
  fillOf: (n) => n.color,
  edgeClasses: (e) => e.confidence,
  onNodeTap: (data) => showPanel(data),
  onBgTap: () => closePanel(),
});

// ── File group summaries (for visual grouping tooltips) ─────────────────────
// We show a single custom tooltip (the styled div) on hover/click over the
// file group containers (the rounded boxes produced when "Group by file" is on).
// We deliberately do NOT inject native SVG <title> elements, which would cause
// the browser to show a second, duplicate native tooltip with the same text.
const FILE_SUMMARIES = (GRAPH_DATA && GRAPH_DATA.fileSummaries) || {};
const groupTipEl = document.getElementById('group-tooltip');

// HTML escape for untrusted content (LLM summaries, and defensively for node
// labels that end up in innerHTML-constructed UI). The group tooltip uses
// textContent (safe); the info panel builds HTML strings, so we must escape
// before interpolation.
function escapeHtml(s) {
  s = (s == null ? '' : String(s));
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function _positionGroupTip(x, y) {
  if (!groupTipEl) return;
  groupTipEl.style.left = (x + 14) + 'px';
  groupTipEl.style.top = (y + 10) + 'px';
}
function showGroupTooltip(text, x, y) {
  if (!groupTipEl || !text) return;
  groupTipEl.textContent = text;
  _positionGroupTip(x, y);
  groupTipEl.style.display = 'block';
}
function hideGroupTooltip() {
  if (groupTipEl) groupTipEl.style.display = 'none';
}
if (gv && gv.svg) {
  gv.svg.addEventListener('mousemove', (e) => {
    const g = e.target && e.target.closest ? e.target.closest('.gv-group') : null;
    if (g) {
      const lbl = g.querySelector ? g.querySelector('text') : null;
      const key = (lbl && lbl.textContent ? lbl.textContent.trim() : '');
      const sum = FILE_SUMMARIES[key];
      if (sum) {
        showGroupTooltip(sum, e.clientX, e.clientY);
        return;
      }
    }
    hideGroupTooltip();
  });
  gv.svg.addEventListener('mouseleave', hideGroupTooltip);
  // Click on a group box also surfaces its summary via the same tooltip.
  gv.svg.addEventListener('click', (e) => {
    const g = e.target && e.target.closest ? e.target.closest('.gv-group') : null;
    if (g) {
      const lbl = g.querySelector ? g.querySelector('text') : null;
      const key = (lbl && lbl.textContent ? lbl.textContent.trim() : '');
      const sum = FILE_SUMMARIES[key];
      if (sum) {
        showGroupTooltip(sum, e.clientX, e.clientY);
      }
    }
  });
}

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

  const fileKey = data.relative_file || data.file || '';
  const fileSum = (GRAPH_DATA.fileSummaries && GRAPH_DATA.fileSummaries[fileKey]) ? GRAPH_DATA.fileSummaries[fileKey] : '';
  const safeFileSum = fileSum ? escapeHtml(fileSum) : '';
  const safeSummary = data.summary ? escapeHtml(data.summary) : '';
  panelMeta.innerHTML = isExternal
    ? `
    <div class="info-row"><span class="info-label">Lang</span><span class="info-val">${badge}</span></div>
    <div class="info-row"><span class="info-label">Kind</span><span class="info-val">External / stdlib / builtin (no definition in this project)</span></div>
  `
    : `
    <div class="info-row"><span class="info-label">Lang</span><span class="info-val">${badge}</span></div>
    <div class="info-row"><span class="info-label">File</span><span class="info-val" title="${escapeHtml(data.file || '')}">${escapeHtml(file)}</span></div>
    <div class="info-row"><span class="info-label">Lines</span><span class="info-val">${lines}</span></div>
    ${data.class_name ? `<div class="info-row"><span class="info-label">Class</span><span class="info-val">${escapeHtml(data.class_name)}</span></div>` : ''}
    <div class="info-row"><span class="info-label">Flow</span><span class="info-val">${data.is_entrypoint ? '🟢 Entrypoint (flow root)' : 'depth ' + data.depth + ' from entrypoint'}</span></div>
    ${data.summary ? `<div class="info-row"><span class="info-label">Summary</span><span class="info-val">${safeSummary}</span></div>` : ''}
    ${fileSum ? `<div class="info-row"><span class="info-label">File&nbsp;role</span><span class="info-val">${safeFileSum}</span></div>` : ''}
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
        if (!t) return '';
        const f = escapeHtml(t.relative_file || t.file || '');
        const q = escapeHtml(t.qualified_name || t.name || '');
        return `<span class="fn-link" data-id="${tid}" title="${f}: ${q}">${q}</span>`;
      }).join('')
    : '';

  // Callers
  const callerIds = [...new Set(callerMap[data.id] || [])];
  callersSection.innerHTML = callerIds.length
    ? `<div class="section-title">Called by (${callerIds.length})</div>` +
      callerIds.map((sid) => {
        const s = nodeById[sid];
        if (!s) return '';
        const f = escapeHtml(s.relative_file || s.file || '');
        const q = escapeHtml(s.qualified_name || s.name || '');
        return `<span class="fn-link" data-id="${sid}" title="${f}: ${q}">${q}</span>`;
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

// Toggle file-container grouping, then re-run the current layout.
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
  ? ENTRYPOINTS.map((n) => {
      const q = escapeHtml(n.qualified_name || n.name || '');
      const f = escapeHtml(n.relative_file || n.file || '');
      return `<div class="flow-item" data-id="${n.id}">` +
             `<div class="fi-name">${q}</div>` +
             `<div class="fi-file">${f}</div></div>`;
    }).join('')
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
      const q = escapeHtml(n.qualified_name || n.name || '');
      const f = escapeHtml(n.relative_file || n.file || '');
      return `<div class="sr-item" data-id="${n.id}">
        <span class="sr-name">${q}</span>
        <span class="sr-file">${f}</span>
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
