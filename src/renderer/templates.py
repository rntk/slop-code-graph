"""HTML skeleton and placeholder-based template for the self-contained output.

The template uses str.replace (not str.format) with @@PLACEHOLDER@@ tokens so
that embedded CSS/JS (which contain { } and other characters) do not need escaping.
"""

# Placeholders used by render():
#   @@TITLE@@ @@ENGINE@@ @@APP@@ @@FLOWSTYLE@@ @@FLOWSCRIPT@@ @@GRAPHDATA@@ @@TREEMAPSTYLE@@ @@TREEMAPSCRIPT@@

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Call Graph — @@TITLE@@</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
  background: #1e1e1e;
  color: #d4d4d4;
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ── Toolbar ── */
#toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: #252526;
  border-bottom: 1px solid #3c3c3c;
  flex-shrink: 0;
  flex-wrap: wrap;
}

#title {
  font-weight: 600;
  font-size: 13px;
  color: #ccc;
  white-space: nowrap;
  margin-right: 4px;
}

#search-wrap {
  position: relative;
  flex: 1;
  min-width: 180px;
  max-width: 360px;
}

#search {
  width: 100%;
  padding: 5px 10px 5px 30px;
  background: #3c3c3c;
  border: 1px solid #555;
  border-radius: 4px;
  color: #d4d4d4;
  font-size: 13px;
  outline: none;
}
#search:focus { border-color: #007acc; }
#search-icon {
  position: absolute;
  left: 8px;
  top: 50%;
  transform: translateY(-50%);
  color: #888;
  font-size: 13px;
  pointer-events: none;
}
#search-count {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 11px;
  color: #888;
}

.tb-sep { width: 1px; height: 20px; background: #3c3c3c; }

.tb-btn {
  padding: 4px 10px;
  background: #3c3c3c;
  border: 1px solid #555;
  border-radius: 4px;
  color: #d4d4d4;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}
.tb-btn:hover { background: #4a4a4a; border-color: #777; }
.tb-btn.active { background: #007acc; border-color: #007acc; color: #fff; }
#flows-wrap { position: relative; display: inline-block; }
#flows-menu {
  display: none; position: absolute; top: 100%; left: 0; margin-top: 4px; z-index: 50;
  background: #252526; border: 1px solid #555; border-radius: 4px; min-width: 240px;
  max-height: 360px; overflow-y: auto; box-shadow: 0 6px 18px rgba(0,0,0,0.5);
}
#flows-menu.open { display: block; }
.flow-item { padding: 6px 10px; cursor: pointer; border-bottom: 1px solid #333; }
.flow-item:last-child { border-bottom: none; }
.flow-item:hover { background: #094771; }
.flow-item .fi-name { color: #d4d4d4; font-weight: 600; font-size: 12px; }
.flow-item .fi-file { color: #888; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.flow-item .fi-empty { color: #888; padding: 8px 10px; font-style: italic; }

select.tb-btn {
  padding: 4px 6px;
  min-width: 130px;
}
.topic-levels {
  display: inline-flex;
  gap: 4px;
  align-items: center;
}
.topic-level-btn {
  min-width: 32px;
  padding-left: 7px;
  padding-right: 7px;
}

/* ── Main area ── */
#main {
  display: flex;
  flex: 1;
  overflow: hidden;
}

#cy {
  flex: 1;
  background: #1a1a2e;
  background-image:
    radial-gradient(circle, #2a2a40 1px, transparent 1px);
  background-size: 28px 28px;
}

/* ── SVG graph engine ── */
.gv-svg { width: 100%; height: 100%; display: block; touch-action: none; }
/* Group containers: translucent boxes drawn behind the function nodes. File
   grouping uses one level; Canvas-topic grouping can nest topic levels. */
.gv-group-box {
  fill: rgba(255, 255, 255, 0.025);
  stroke: #565676;
  stroke-width: 1.5px;
  stroke-opacity: 0.7;
}
.gv-group-label {
  font-size: 12px;
  font-weight: 600;
  fill: #9aa0c0;
  pointer-events: none;
  dominant-baseline: middle;
  opacity: 0.9;
}
.gv-group.depth-1 .gv-group-box { fill: rgba(255, 255, 255, 0.018); stroke-opacity: 0.62; }
.gv-group.depth-2 .gv-group-box { fill: rgba(255, 255, 255, 0.012); stroke-opacity: 0.56; }
.gv-group.depth-3 .gv-group-box,
.gv-group.depth-4 .gv-group-box { fill: rgba(255, 255, 255, 0.008); stroke-opacity: 0.5; }
.gv-group.depth-1 .gv-group-label,
.gv-group.depth-2 .gv-group-label,
.gv-group.depth-3 .gv-group-label,
.gv-group.depth-4 .gv-group-label { font-size: 11px; }
.node { cursor: pointer; }
.node .shape { stroke-width: 0; }
.node .nlabel { font-size: 11px; font-weight: 600; fill: #1e1e1e; pointer-events: none; }
.node.external .shape { fill-opacity: 0.55; stroke: #8a8aa6; stroke-width: 1px; stroke-dasharray: 4 3; }
.node.external .nlabel { fill: #c8c8d8; font-style: italic; font-weight: 400; }
/* Flow entrypoints (roots): functions in the selected scope that nothing in
   the pruned graph calls — i.e. where a flow starts. */
.node.entrypoint .shape { stroke: #4ec9b0; stroke-width: 3px; stroke-opacity: 0.95; filter: drop-shadow(0 0 4px rgba(78,201,176,0.6)); }
.node.entrypoint .nlabel { font-weight: 700; }
/* Summary-only mode: one node per file showing the LLM description */
.node.summary-node .shape {
  fill: #2a2a42 !important;
  stroke: #6a6a8e;
  stroke-width: 2px;
  stroke-opacity: 0.9;
}
.node.summary-node .nlabel { font-size: 11px; font-weight: 400; fill: #e8eaf4; }
.node.summary-node.entrypoint .shape {
  fill: #243038 !important;
  stroke: #4ec9b0;
  stroke-width: 2.5px;
}
.node.summary-node.entrypoint .nlabel tspan:first-child { font-weight: 700; font-size: 12px; fill: #6ee7c8; }
.node.selected .shape { stroke: #ffffff; stroke-width: 3px; stroke-opacity: 0.9; }
.node.highlighted .shape { stroke: #ffcc00; stroke-width: 2px; }
.node.dimmed { opacity: 0.15; }
.edge { fill: none; stroke: #7878b8; stroke-width: 2.5px; opacity: 0.85; }
.edge.possible { stroke: #9090b8; stroke-dasharray: 5 3; opacity: 0.5; }
.edge.external { stroke: #7070a0; stroke-dasharray: 1 4; opacity: 0.45; stroke-width: 1.5px; }
.edge.dimmed { opacity: 0.04; }
.edge.highlighted, .edge.selected { stroke: #ffcc00; opacity: 1; stroke-width: 3.5px; }
.edge-label { font-size: 9px; fill: #cfcfe6; pointer-events: none; }
.edge-label-bg { fill: #1a1a2e; }

/* File-group LLM summary tooltip (hover/click on the translucent file containers) */
.group-tooltip {
  position: fixed;
  display: none;
  max-width: 360px;
  background: #111113;
  color: #d4d4d4;
  border: 1px solid #565676;
  border-radius: 4px;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.35;
  z-index: 99999;
  pointer-events: none;
  box-shadow: 0 6px 18px rgba(0,0,0,0.6);
  white-space: pre-wrap;
}

/* ── Info panel ── */
#panel {
  width: 340px;
  min-width: 340px;
  background: #252526;
  border-left: 1px solid #3c3c3c;
  display: flex;
  flex-direction: column;
  transform: translateX(340px);
  transition: transform .2s ease;
  overflow: hidden;
}
#panel.open { transform: translateX(0); }

#panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px 8px;
  border-bottom: 1px solid #3c3c3c;
  flex-shrink: 0;
}
#panel-title {
  font-size: 14px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
#panel-close {
  cursor: pointer;
  color: #888;
  font-size: 16px;
  line-height: 1;
  padding: 2px 4px;
  border-radius: 3px;
}
#panel-close:hover { color: #d4d4d4; background: #3c3c3c; }

#panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.info-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-bottom: 6px;
  font-size: 12px;
}
.info-label {
  color: #888;
  min-width: 52px;
  flex-shrink: 0;
}
.info-val { color: #d4d4d4; word-break: break-all; }
.lang-badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  color: #1e1e1e;
}

.section-title {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: #888;
  margin: 12px 0 6px;
  padding-bottom: 4px;
  border-bottom: 1px solid #3c3c3c;
}

.fn-link {
  display: block;
  font-size: 12px;
  color: #9cdcfe;
  cursor: pointer;
  padding: 2px 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fn-link:hover { color: #4fc1ff; text-decoration: underline; }

#source-wrap {
  margin-top: 12px;
}
#source-code {
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 11px;
  background: #1e1e1e;
  border: 1px solid #3c3c3c;
  border-radius: 4px;
  padding: 8px;
  overflow-x: auto;
  white-space: pre;
  color: #d4d4d4;
  max-height: 300px;
  overflow-y: auto;
  line-height: 1.5;
}

/* ── Status bar ── */
#statusbar {
  padding: 3px 12px;
  font-size: 11px;
  color: #888;
  background: #007acc;
  flex-shrink: 0;
  display: flex;
  gap: 16px;
}
#statusbar span { color: #fff; }

/* ── Search results dropdown ── */
#search-results {
  display: none;
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  background: #252526;
  border: 1px solid #555;
  border-radius: 4px;
  max-height: 240px;
  overflow-y: auto;
  z-index: 1000;
  box-shadow: 0 4px 12px rgba(0,0,0,.5);
}
#search-results.visible { display: block; }
.sr-item {
  padding: 6px 10px;
  font-size: 12px;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.sr-item:hover { background: #3c3c3c; }
.sr-name { color: #d4d4d4; font-weight: 500; }
.sr-file { color: #888; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

@@FLOWSTYLE@@
@@TREEMAPSTYLE@@
@@CANVASSTYLE@@
</style>
</head>
<body>

<div id="toolbar">
  <span id="title">📊 @@TITLE@@</span>
  <div class="tb-sep"></div>

  <div class="tb-tabs">
    <button class="tb-btn tb-tab active" data-view="graph" title="Function call graph">⛓ Call graph</button>
    <button class="tb-btn tb-tab" data-view="treemap" title="File / module tree map">▦ Tree map</button>
    <button class="tb-btn tb-tab" id="tab-canvas" data-view="canvas" title="LLM topic canvas (requires LLM summaries)" style="display:none">🗂 Canvas</button>
  </div>

  <div class="tb-sep"></div>

  <div id="search-wrap">
    <span id="search-icon">🔍</span>
    <input id="search" type="text" placeholder="Search functions…" autocomplete="off" spellcheck="false">
    <span id="search-count"></span>
    <div id="search-results"></div>
  </div>

  <div class="tb-sep"></div>

  <select id="layout-select" class="tb-btn" title="Graph layout" data-graph-only>
    <option value="dagre-lr">Hierarchical →</option>
    <option value="dagre-tb">Hierarchical ↓</option>
    <option value="cose">Force-directed</option>
    <option value="concentric">Concentric</option>
  </select>

  <button class="tb-btn" id="btn-fit" title="Fit all nodes in view" data-graph-only>Fit</button>
  <button class="tb-btn" id="btn-zoom-in" title="Zoom in" data-graph-only>＋</button>
  <button class="tb-btn" id="btn-zoom-out" title="Zoom out" data-graph-only>－</button>

  <div class="tb-sep" data-graph-only></div>

  <button class="tb-btn active" id="btn-possible" title="Toggle low-confidence edges" data-graph-only>Possible edges</button>
  <button class="tb-btn active" id="btn-external" title="Toggle external / stdlib / builtin calls" data-graph-only>External calls</button>
  <button class="tb-btn active" id="btn-group" title="Toggle graph group containers" data-graph-only>Grouping on</button>
  <select id="group-select" class="tb-btn" title="Graph grouping source" data-graph-only>
    <option value="file">Files</option>
  </select>
  <span id="topic-levels" class="topic-levels" data-graph-only style="display:none"></span>
  <button class="tb-btn" id="btn-summary" title="Show file summaries instead of function names (requires LLM summaries)" data-graph-only style="display:none">Summary only</button>

  <div class="tb-sep" data-graph-only></div>

  <div id="flows-wrap" data-graph-only>
    <button class="tb-btn" id="btn-flows" title="Jump to a flow entrypoint">Flows ▾</button>
    <div id="flows-menu"></div>
  </div>
  <button class="tb-btn" id="btn-reset-flow" title="Show the whole graph again" data-graph-only style="display:none">Show all</button>
</div>

<div id="main">
  <div id="cy"></div>

  <div id="treemap">
    <div id="treemap-bar">
      <span id="treemap-crumbs"></span>
      <span style="flex:1"></span>
      <span id="treemap-hint">click: details&nbsp;&nbsp;double-click: drill into file</span>
    </div>
    <div id="treemap-canvas"></div>
  </div>

  <div id="canvas-view"></div>

  <div id="flow-view">
    <div id="flow-bar">
      <button class="tb-btn" id="flow-back">← Call graph</button>
      <span id="flow-title"></span>
      <span id="flow-hint">▭ step&nbsp;&nbsp;◆ condition&nbsp;&nbsp;⬡ loop&nbsp;&nbsp;↺ back-edge</span>
      <span style="flex:1"></span>
      <button class="tb-btn" id="flow-fit">Fit</button>
    </div>
    <div id="flow-cy"></div>
  </div>

  <div id="panel">
    <div id="panel-header">
      <span id="panel-title"></span>
      <span id="panel-close" title="Close">✕</span>
    </div>
    <div id="panel-body">
      <div id="panel-meta"></div>
      <button class="tb-btn" id="btn-flow" style="display:none;width:100%;margin-bottom:4px">▦ View flowchart (conditions & loops) ▸</button>
      <button class="tb-btn" id="btn-isolate" style="display:none;width:100%;margin-bottom:4px">⇣ Isolate downstream flow ▸</button>
      <div id="source-wrap">
        <div class="section-title">Source</div>
        <pre id="source-code"></pre>
      </div>
      <div id="callees-section"></div>
      <div id="callers-section"></div>
    </div>
  </div>
</div>

<div id="statusbar">
  <span id="stat-nodes">0 functions</span>
  <span id="stat-edges">0 edges</span>
  <span id="stat-files">0 files</span>
  <span id="stat-selection"></span>
</div>

<div id="group-tooltip" class="group-tooltip"></div>

<script>
@@ENGINE@@
</script>

<script>
@@APP@@
</script>

<script>
@@FLOWSCRIPT@@
</script>

<script>
@@TREEMAPSCRIPT@@
</script>

<script>
@@CANVASSCRIPT@@
</script>
</body>
</html>
"""
