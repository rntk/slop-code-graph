"""Main call-graph application script (built on GraphView).

Injected verbatim into the generated HTML via the @@APP@@ placeholder.
"""

APP_SCRIPT = r"""
// ── Data ──────────────────────────────────────────────────────────────────
const GRAPH_DATA = @@GRAPHDATA@@;
const HAS_CANVAS_TOPICS = !!(GRAPH_DATA && GRAPH_DATA.canvas
  && Array.isArray(GRAPH_DATA.canvas.topics)
  && GRAPH_DATA.canvas.topics.length
  && Array.isArray(GRAPH_DATA.canvas.lineMeta));

function splitTopicPath(path) {
  return String(path || '').split('>').map((p) => p.trim()).filter(Boolean);
}

function buildTopicGraphIndex() {
  const empty = { nodeTopicPath: {}, topicSummaries: {}, maxLevel: 0 };
  if (!HAS_CANVAS_TOPICS) return empty;
  const canvas = GRAPH_DATA.canvas;
  const counts = {};
  const prefixSummaries = {};
  canvas.topics.forEach((t) => {
    const parts = splitTopicPath(t.path || t.name);
    if (!parts.length) return;
    const path = parts.join('>');
    empty.topicSummaries[path] = t.summary || '';
    empty.maxLevel = Math.max(empty.maxLevel, parts.length - 1);
    for (let i = 1; i <= parts.length; i++) {
      const prefix = parts.slice(0, i).join('>');
      if (!prefixSummaries[prefix]) prefixSummaries[prefix] = [];
      if (t.summary) prefixSummaries[prefix].push(t.summary);
    }
    (t.ranges || []).forEach((r) => {
      const start = Math.max(0, Number(r.start) || 0);
      const end = Math.min(canvas.lineMeta.length - 1, Number(r.end) || start);
      for (let i = start; i <= end; i++) {
        const meta = canvas.lineMeta[i] || {};
        const nid = meta.nodeId || '';
        if (!nid) continue;
        if (!counts[nid]) counts[nid] = {};
        counts[nid][path] = (counts[nid][path] || 0) + 1;
      }
    });
  });
  Object.entries(counts).forEach(([nid, byPath]) => {
    let bestPath = '', bestCount = -1;
    Object.entries(byPath).forEach(([path, count]) => {
      if (count > bestCount || (count === bestCount && path.length > bestPath.length)) {
        bestPath = path;
        bestCount = count;
      }
    });
    if (bestPath) empty.nodeTopicPath[nid] = splitTopicPath(bestPath);
  });
  Object.entries(prefixSummaries).forEach(([path, summaries]) => {
    if (!empty.topicSummaries[path] && summaries.length) {
      empty.topicSummaries[path] = summaries.slice(0, 4).join('\n\n');
    }
  });
  return empty;
}

const TOPIC_GRAPH = buildTopicGraphIndex();
let groupMode = 'file';
let topicLevel = 0;

// ── Graph engine init ───────────────────────────────────────────────────────
const gv = new GraphView(document.getElementById('cy'), {
  nodes: GRAPH_DATA.nodes,
  edges: GRAPH_DATA.edges,
  nodeClasses: (n) => n.language + (n.language === 'external' ? ' external' : '') + (n.is_entrypoint ? ' entrypoint' : ''),
  shapeOf: (n) => (n.language === 'external' ? 'round-tag' : 'round-rectangle'),
  // Group function nodes into file or Canvas-topic containers in graph layouts.
  // External (stdlib/builtin) nodes are deduped across files/topics, so they
  // stay ungrouped (null).
  groupOf: (n) => {
    if (n.language === 'external') return null;
    if (groupMode === 'topic') {
      const p = TOPIC_GRAPH.nodeTopicPath[n.id];
      return p && p.length ? p.slice(0, topicLevel + 1).join('>') : 'Uncategorized';
    }
    return n.relative_file || n.file || null;
  },
  groupPathOf: (n) => {
    if (n.language === 'external') return null;
    if (groupMode !== 'topic') return [n.relative_file || n.file || 'Unknown file'];
    const p = TOPIC_GRAPH.nodeTopicPath[n.id];
    return p && p.length ? p.slice(0, topicLevel + 1) : ['Uncategorized'];
  },
  groupLabelOf: (key) => groupMode === 'topic' ? (splitTopicPath(key).slice(-1)[0] || key) : key,
  groupColorOf: (key, depth) => {
    if (groupMode !== 'topic') return null;
    const colors = ['#4ec9b0', '#dcdcaa', '#c586c0', '#9cdcfe', '#ce9178'];
    return colors[Math.max(0, depth || 0) % colors.length];
  },
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
      const key = (g.dataset && g.dataset.groupKey)
        || (lbl && lbl.textContent ? lbl.textContent.trim() : '');
      const sum = groupMode === 'topic' ? TOPIC_GRAPH.topicSummaries[key] : FILE_SUMMARIES[key];
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
      const key = (g.dataset && g.dataset.groupKey)
        || (lbl && lbl.textContent ? lbl.textContent.trim() : '');
      const sum = groupMode === 'topic' ? TOPIC_GRAPH.topicSummaries[key] : FILE_SUMMARIES[key];
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
  const fileKey = data.relative_file || data.file || '';
  const summaryInfo = summaryOnly ? proxySummaryInfo[data.id] : null;
  const isSummaryNode = !!summaryInfo;
  const title = isSummaryNode ? summaryInfo.title : (data.qualified_name || data.name);
  panelTitle.textContent = title;
  panelTitle.title = title;

  const isExternal = data.language === 'external';
  const badge = `<span class="lang-badge" style="background:${data.color}">${data.language}</span>`;
  const file = data.relative_file || data.file;
  const lines = `L${data.start_line}–${data.end_line}`;

  const fileSum = (GRAPH_DATA.fileSummaries && GRAPH_DATA.fileSummaries[fileKey]) ? GRAPH_DATA.fileSummaries[fileKey] : '';
  const safeFileSum = fileSum ? escapeHtml(fileSum) : '';
  const proxySummary = summaryInfo && summaryInfo.summary ? escapeHtml(summaryInfo.summary) : '';
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
    ${proxySummary ? `<div class="info-row"><span class="info-label">${summaryInfo.kind === 'topic' ? 'Topic&nbsp;summary' : 'Description'}</span><span class="info-val">${proxySummary}</span></div>` : ''}
    ${!summaryInfo && fileSum ? `<div class="info-row"><span class="info-label">File&nbsp;role</span><span class="info-val">${safeFileSum}</span></div>` : ''}
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
let summaryOnly = false;
function refreshGroupControls() {
  const groupBtn = document.getElementById('btn-group');
  const modeSelect = document.getElementById('group-select');
  const levels = document.getElementById('topic-levels');
  const topicSummaryActive = summaryOnly && summaryKind() === 'topic';
  const controlsVisible = groupByFile || topicSummaryActive;
  groupBtn.classList.toggle('active', controlsVisible);
  groupBtn.textContent = controlsVisible ? 'Grouping on' : 'Grouping off';
  modeSelect.style.display = controlsVisible ? '' : 'none';
  modeSelect.value = groupMode;
  levels.style.display = controlsVisible && groupMode === 'topic' ? '' : 'none';
  levels.querySelectorAll('button').forEach((btn) => {
    btn.classList.toggle('active', Number(btn.dataset.level) === topicLevel);
  });
}
window.refreshGroupControls = refreshGroupControls;

function rebuildTopicLevelButtons() {
  const levels = document.getElementById('topic-levels');
  levels.innerHTML = '';
  for (let i = 0; i <= TOPIC_GRAPH.maxLevel; i++) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'tb-btn topic-level-btn';
    btn.dataset.level = String(i);
    btn.textContent = 'L' + i;
    btn.title = 'Show Canvas topic level ' + i;
    levels.appendChild(btn);
  }
}

if (HAS_CANVAS_TOPICS) {
  const groupSelect = document.getElementById('group-select');
  const opt = document.createElement('option');
  opt.value = 'topic';
  opt.textContent = 'Canvas topics';
  groupSelect.appendChild(opt);
  rebuildTopicLevelButtons();
}
refreshGroupControls();

document.getElementById('btn-group').addEventListener('click', function () {
  if (summaryOnly) return;
  groupByFile = !groupByFile;
  gv.setGrouping(groupByFile);
  refreshGroupControls();
  applyLayout(document.getElementById('layout-select').value);
});
document.getElementById('group-select').addEventListener('change', function () {
  if (summaryOnly) return;
  groupMode = this.value === 'topic' && HAS_CANVAS_TOPICS ? 'topic' : 'file';
  gv.setGrouping(groupByFile);
  refreshGroupControls();
  updateSummaryButtonState();
  hideGroupTooltip();
  applyLayout(document.getElementById('layout-select').value);
});
document.getElementById('topic-levels').addEventListener('click', function (e) {
  const btn = e.target.closest('.topic-level-btn');
  if (!btn || (summaryOnly && summaryKind() !== 'topic')) return;
  topicLevel = Math.max(0, Math.min(TOPIC_GRAPH.maxLevel, Number(btn.dataset.level) || 0));
  refreshGroupControls();
  hideGroupTooltip();
  if (summaryOnly) {
    applySummaryNodeState();
  }
  applyLayout(document.getElementById('layout-select').value);
});

// ── Summary-only view (file/topic blocks with LLM descriptions) ───────────
// Collapses each summarized file, or each visible Canvas topic level, to a
// single node showing its LLM description. Cross-block call edges are preserved
// by rewriting edge endpoints to the chosen proxy nodes.
const HAS_FILE_SUMMARIES = Object.keys(FILE_SUMMARIES).length > 0;
const HAS_TOPIC_SUMMARIES = Object.keys(TOPIC_GRAPH.topicSummaries).length > 0;
const fileProxy = {};   // relative_file -> representative node id
const proxyFileKey = {}; // node id -> relative_file
const topicProxy = {};   // topic prefix at current level -> representative node id
const proxyTopicKey = {}; // node id -> topic prefix
const proxySummaryInfo = {}; // node id -> { kind, key, title, summary }
const defaultLabelOf = (n) => (n.class_name ? n.class_name + '.' + n.name : n.name);

function nodeFileKey(n) {
  return n.language === 'external' ? null : (n.relative_file || n.file || null);
}

function wrapSummaryText(text, maxLen) {
  const words = String(text || '').split(/\s+/);
  const lines = [];
  let line = '';
  words.forEach((w) => {
    const next = line ? line + ' ' + w : w;
    if (next.length > maxLen && line) { lines.push(line); line = w; }
    else line = next;
  });
  if (line) lines.push(line);
  return lines.slice(0, 10).join('\n');
}

function summaryNodeLabel(fileKey) {
  const base = fileKey.split('/').pop() || fileKey;
  const sum = FILE_SUMMARIES[fileKey] || '';
  return base + '\n' + wrapSummaryText(sum, 44);
}

function topicTitle(topicKey) {
  return splitTopicPath(topicKey).slice(-1)[0] || topicKey;
}

function topicSummaryNodeLabel(topicKey) {
  const sum = TOPIC_GRAPH.topicSummaries[topicKey] || '';
  return topicTitle(topicKey) + '\n' + wrapSummaryText(sum, 44);
}

function nodeTopicKey(n) {
  if (!n || n.language === 'external') return null;
  const p = TOPIC_GRAPH.nodeTopicPath[n.id];
  if (!p || !p.length) return null;
  return p.slice(0, Math.min(topicLevel + 1, p.length)).join('>');
}

function clearObject(obj) {
  Object.keys(obj).forEach((k) => { delete obj[k]; });
}

if (HAS_FILE_SUMMARIES) {
  const byFile = {};
  GRAPH_DATA.nodes.forEach((n) => {
    const k = nodeFileKey(n);
    if (!k || !FILE_SUMMARIES[k]) return;
    if (!byFile[k]) byFile[k] = [];
    byFile[k].push(n);
  });
  Object.entries(byFile).forEach(([k, nodes]) => {
    nodes.sort((a, b) => {
      if (a.is_entrypoint !== b.is_entrypoint) return a.is_entrypoint ? -1 : 1;
      if (a.depth !== b.depth) return a.depth - b.depth;
      return (a.start_line || 0) - (b.start_line || 0);
    });
    fileProxy[k] = nodes[0].id;
    proxyFileKey[nodes[0].id] = k;
  });
}

const savedLabels = new Map();
let savedGroupByFile = true;
const SUMMARY_NODE_FILL = '#2a2a42';
let savedFillOf = null;

function rebuildTopicProxies() {
  clearObject(topicProxy);
  clearObject(proxyTopicKey);
  const byTopic = {};
  GRAPH_DATA.nodes.forEach((n) => {
    const k = nodeTopicKey(n);
    if (!k || !TOPIC_GRAPH.topicSummaries[k]) return;
    if (!byTopic[k]) byTopic[k] = [];
    byTopic[k].push(n);
  });
  Object.entries(byTopic).forEach(([k, nodes]) => {
    nodes.sort((a, b) => {
      if (a.is_entrypoint !== b.is_entrypoint) return a.is_entrypoint ? -1 : 1;
      if (a.depth !== b.depth) return a.depth - b.depth;
      return (a.start_line || 0) - (b.start_line || 0);
    });
    topicProxy[k] = nodes[0].id;
    proxyTopicKey[nodes[0].id] = k;
  });
}

function summaryKind() {
  return groupMode === 'topic' && HAS_TOPIC_SUMMARIES ? 'topic' : 'file';
}

function hasCurrentSummaryData() {
  return summaryKind() === 'topic' ? HAS_TOPIC_SUMMARIES : HAS_FILE_SUMMARIES;
}

function updateSummaryButtonState() {
  const btn = document.getElementById('btn-summary');
  const hasAny = HAS_FILE_SUMMARIES || HAS_TOPIC_SUMMARIES;
  btn.style.display = hasAny ? '' : 'none';
  btn.disabled = hasAny && !hasCurrentSummaryData();
  btn.title = summaryKind() === 'topic'
    ? 'Show Canvas topic summaries instead of function names'
    : 'Show file summaries instead of function names (requires LLM summaries)';
}

function applySummaryNodeState() {
  const kind = summaryKind();
  clearObject(proxySummaryInfo);
  clearObject(proxyTopicKey);
  if (kind === 'topic') rebuildTopicProxies();

  gv.o.endpointOf = (id) => {
    const n = nodeById[id];
    if (!n) return id;
    if (kind === 'topic') {
      const tk = nodeTopicKey(n);
      return (tk && topicProxy[tk]) ? topicProxy[tk] : id;
    }
    const fk = nodeFileKey(n);
    return (fk && fileProxy[fk]) ? fileProxy[fk] : id;
  };

  if (!savedFillOf) savedFillOf = gv.o.fillOf;
  gv.o.fillOf = (n) => (
    proxySummaryInfo[n.id] ? SUMMARY_NODE_FILL : (savedFillOf ? savedFillOf(n) : n.color)
  );

  gv.forEachNode((id, n) => {
    if (kind === 'topic') {
      const tk = nodeTopicKey(n);
      const proxyId = tk ? topicProxy[tk] : null;
      if (tk && proxyId && id === proxyId) {
        if (!savedLabels.has(id)) savedLabels.set(id, defaultLabelOf(n));
        proxySummaryInfo[id] = {
          kind: 'topic',
          key: tk,
          title: topicTitle(tk),
          summary: TOPIC_GRAPH.topicSummaries[tk] || '',
        };
        gv.nodeClass(id, 'summary-node', true);
        gv.showNode(id, true);
        gv.setNodeLabel(id, topicSummaryNodeLabel(tk));
      } else {
        gv.nodeClass(id, 'summary-node', false);
        gv.showNode(id, false);
        if (savedLabels.has(id)) gv.setNodeLabel(id, savedLabels.get(id));
      }
      return;
    }

    if (n.language === 'external') return;
    const fk = nodeFileKey(n);
    if (fk && fileProxy[fk]) {
      if (id === fileProxy[fk]) {
        if (!savedLabels.has(id)) savedLabels.set(id, defaultLabelOf(n));
        proxySummaryInfo[id] = {
          kind: 'file',
          key: fk,
          title: fk,
          summary: FILE_SUMMARIES[fk] || '',
        };
        gv.nodeClass(id, 'summary-node', true);
        gv.showNode(id, true);
        gv.setNodeLabel(id, summaryNodeLabel(fk));
      } else {
        gv.nodeClass(id, 'summary-node', false);
        gv.showNode(id, false);
        if (savedLabels.has(id)) gv.setNodeLabel(id, savedLabels.get(id));
      }
    }
  });
  gv._redraw();
}

function applySummaryMode(on) {
  if (on && !hasCurrentSummaryData()) return;
  summaryOnly = on;
  const btn = document.getElementById('btn-summary');
  const groupBtn = document.getElementById('btn-group');
  const groupSelect = document.getElementById('group-select');
  const topicLevels = document.getElementById('topic-levels');
  const allowTopicLevels = on && summaryKind() === 'topic';
  btn.classList.toggle('active', on);
  groupBtn.style.opacity = on ? '0.45' : '';
  groupBtn.style.pointerEvents = on ? 'none' : '';
  groupSelect.style.opacity = on ? '0.45' : '';
  groupSelect.style.pointerEvents = on ? 'none' : '';
  topicLevels.style.opacity = on && !allowTopicLevels ? '0.45' : '';
  topicLevels.style.pointerEvents = on && !allowTopicLevels ? 'none' : '';
  if (allowTopicLevels) topicLevels.style.display = '';

  if (on) {
    savedGroupByFile = groupByFile;
    if (summaryKind() === 'topic') {
      groupByFile = true;
      gv.setGrouping(true);
    } else {
      groupByFile = false;
      gv.setGrouping(false);
    }
    refreshGroupControls();
    applySummaryNodeState();
  } else {
    gv.o.endpointOf = null;
    if (savedFillOf) gv.o.fillOf = savedFillOf;
    savedFillOf = null;
    clearObject(proxySummaryInfo);
    clearObject(proxyTopicKey);
    gv.forEachNode((id, n) => {
      gv.nodeClass(id, 'summary-node', false);
      gv.showNode(id, true);
      if (savedLabels.has(id)) gv.setNodeLabel(id, savedLabels.get(id));
    });
    savedLabels.clear();
    groupByFile = savedGroupByFile;
    gv.setGrouping(groupByFile);
    refreshGroupControls();
    gv._redraw();
  }
  updateSummaryButtonState();
  applyLayout(document.getElementById('layout-select').value);
}

document.getElementById('btn-summary').addEventListener('click', function () {
  if (!hasCurrentSummaryData()) return;
  applySummaryMode(!summaryOnly);
});
updateSummaryButtonState();

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
