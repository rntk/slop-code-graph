"""Generate a fully self-contained HTML call-graph visualization."""

from __future__ import annotations

import hashlib
import html
import json
import urllib.request
from pathlib import Path

from .graph_builder import CallGraph

# ---------------------------------------------------------------------------
# JS library fetching
# ---------------------------------------------------------------------------

LIBS = {
    "dagre": "https://unpkg.com/dagre@0.8.5/dist/dagre.min.js",
    "cytoscape": "https://unpkg.com/cytoscape@3.29.2/dist/cytoscape.min.js",
    "cytoscape-dagre": "https://unpkg.com/cytoscape-dagre@2.5.0/cytoscape-dagre.js",
    "fuse": "https://unpkg.com/fuse.js@7.0.0/dist/fuse.min.js",
}

CACHE_DIR = Path.home() / ".cache" / "callgraph"


def _fetch_lib(name: str, url: str) -> str | None:
    """Download a JS library and cache it locally. Returns content or None."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    cache_file = CACHE_DIR / f"{name}-{url_hash}.js"

    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "callgraph/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8")
        cache_file.write_text(content, encoding="utf-8")
        return content
    except Exception as e:
        print(f"  [warn] Could not download {name}: {e}")
        return None


def get_js_bundle() -> tuple[str, bool]:
    """
    Returns (js_bundle_html, is_inline).
    Tries to inline all libraries; falls back to CDN <script> tags.
    """
    parts: list[str] = []
    all_ok = True

    for name, url in LIBS.items():
        content = _fetch_lib(name, url)
        if content:
            parts.append(f"/* {name} */\n{content}")
        else:
            all_ok = False

    if all_ok and parts:
        bundle = "\n\n".join(parts)
        return f"<script>\n{bundle}\n</script>", True
    else:
        # Fall back to CDN tags
        tags = "\n".join(f'<script src="{url}"></script>' for url in LIBS.values())
        return tags, False


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Call Graph — {title}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
  background: #1e1e1e;
  color: #d4d4d4;
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}}

/* ── Toolbar ── */
#toolbar {{
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: #252526;
  border-bottom: 1px solid #3c3c3c;
  flex-shrink: 0;
  flex-wrap: wrap;
}}

#title {{
  font-weight: 600;
  font-size: 13px;
  color: #ccc;
  white-space: nowrap;
  margin-right: 4px;
}}

#search-wrap {{
  position: relative;
  flex: 1;
  min-width: 180px;
  max-width: 360px;
}}

#search {{
  width: 100%;
  padding: 5px 10px 5px 30px;
  background: #3c3c3c;
  border: 1px solid #555;
  border-radius: 4px;
  color: #d4d4d4;
  font-size: 13px;
  outline: none;
}}
#search:focus {{ border-color: #007acc; }}
#search-icon {{
  position: absolute;
  left: 8px;
  top: 50%;
  transform: translateY(-50%);
  color: #888;
  font-size: 13px;
  pointer-events: none;
}}
#search-count {{
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 11px;
  color: #888;
}}

.tb-sep {{ width: 1px; height: 20px; background: #3c3c3c; }}

.tb-btn {{
  padding: 4px 10px;
  background: #3c3c3c;
  border: 1px solid #555;
  border-radius: 4px;
  color: #d4d4d4;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}}
.tb-btn:hover {{ background: #4a4a4a; border-color: #777; }}
.tb-btn.active {{ background: #007acc; border-color: #007acc; color: #fff; }}

select.tb-btn {{
  padding: 4px 6px;
  min-width: 130px;
}}

/* ── Main area ── */
#main {{
  display: flex;
  flex: 1;
  overflow: hidden;
}}

#cy {{
  flex: 1;
  background: #1a1a2e;
  background-image:
    radial-gradient(circle, #2a2a40 1px, transparent 1px);
  background-size: 28px 28px;
}}

/* ── Info panel ── */
#panel {{
  width: 340px;
  min-width: 340px;
  background: #252526;
  border-left: 1px solid #3c3c3c;
  display: flex;
  flex-direction: column;
  transform: translateX(340px);
  transition: transform .2s ease;
  overflow: hidden;
}}
#panel.open {{ transform: translateX(0); }}

#panel-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px 8px;
  border-bottom: 1px solid #3c3c3c;
  flex-shrink: 0;
}}
#panel-title {{
  font-size: 14px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}}
#panel-close {{
  cursor: pointer;
  color: #888;
  font-size: 16px;
  line-height: 1;
  padding: 2px 4px;
  border-radius: 3px;
}}
#panel-close:hover {{ color: #d4d4d4; background: #3c3c3c; }}

#panel-body {{
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}}

.info-row {{
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-bottom: 6px;
  font-size: 12px;
}}
.info-label {{
  color: #888;
  min-width: 52px;
  flex-shrink: 0;
}}
.info-val {{ color: #d4d4d4; word-break: break-all; }}
.lang-badge {{
  display: inline-block;
  padding: 1px 6px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  color: #1e1e1e;
}}

.section-title {{
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: #888;
  margin: 12px 0 6px;
  padding-bottom: 4px;
  border-bottom: 1px solid #3c3c3c;
}}

.fn-link {{
  display: block;
  font-size: 12px;
  color: #9cdcfe;
  cursor: pointer;
  padding: 2px 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}}
.fn-link:hover {{ color: #4fc1ff; text-decoration: underline; }}

#source-wrap {{
  margin-top: 12px;
}}
#source-code {{
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
}}

/* ── Status bar ── */
#statusbar {{
  padding: 3px 12px;
  font-size: 11px;
  color: #888;
  background: #007acc;
  flex-shrink: 0;
  display: flex;
  gap: 16px;
}}
#statusbar span {{ color: #fff; }}

/* ── Search results dropdown ── */
#search-results {{
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
}}
#search-results.visible {{ display: block; }}
.sr-item {{
  padding: 6px 10px;
  font-size: 12px;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  gap: 8px;
}}
.sr-item:hover {{ background: #3c3c3c; }}
.sr-name {{ color: #d4d4d4; font-weight: 500; }}
.sr-file {{ color: #888; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}

{flow_style}
</style>
</head>
<body>

<div id="toolbar">
  <span id="title">📊 {title}</span>
  <div class="tb-sep"></div>

  <div id="search-wrap">
    <span id="search-icon">🔍</span>
    <input id="search" type="text" placeholder="Search functions…" autocomplete="off" spellcheck="false">
    <span id="search-count"></span>
    <div id="search-results"></div>
  </div>

  <div class="tb-sep"></div>

  <select id="layout-select" class="tb-btn" title="Graph layout">
    <option value="dagre-lr">Hierarchical →</option>
    <option value="dagre-tb">Hierarchical ↓</option>
    <option value="cose">Force-directed</option>
    <option value="concentric">Concentric</option>
  </select>

  <button class="tb-btn" id="btn-fit" title="Fit all nodes in view">Fit</button>
  <button class="tb-btn" id="btn-zoom-in" title="Zoom in">＋</button>
  <button class="tb-btn" id="btn-zoom-out" title="Zoom out">－</button>

  <div class="tb-sep"></div>

  <button class="tb-btn active" id="btn-possible" title="Toggle low-confidence edges">Possible edges</button>
  <button class="tb-btn active" id="btn-external" title="Toggle external / stdlib / builtin calls">External calls</button>
</div>

<div id="main">
  <div id="cy"></div>

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

{js_bundle}

<script>
// ── Data ──────────────────────────────────────────────────────────────────
const GRAPH_DATA = {graph_data};

// ── Cytoscape init ────────────────────────────────────────────────────────
cytoscape.use(cytoscapeDagre);

const cy = cytoscape({{
  container: document.getElementById('cy'),
  elements: {{
    nodes: GRAPH_DATA.nodes.map(n => ({{
      data: n,
      classes: n.language,
    }})),
    edges: GRAPH_DATA.edges.map(e => ({{
      data: e,
      classes: e.confidence,
    }})),
  }},
  style: [
    {{
      selector: 'node',
      style: {{
        'label': 'data(name)',
        'background-color': 'data(color)',
        'color': '#1e1e1e',
        'font-size': '11px',
        'font-weight': '600',
        'text-valign': 'center',
        'text-halign': 'center',
        'shape': 'round-rectangle',
        'width': 'label',
        'height': '28px',
        'padding': '8px',
        'border-width': '0px',
        'text-max-width': '160px',
        'text-wrap': 'ellipsis',
      }},
    }},
    {{
      selector: 'node[class_name]',
      style: {{
        'label': (ele) => ele.data('class_name')
          ? `${{ele.data('class_name')}}.${{ele.data('name')}}`
          : ele.data('name'),
      }},
    }},
    {{
      selector: 'node.external',
      style: {{
        'shape': 'round-tag',
        'background-color': 'data(color)',
        'background-opacity': 0.55,
        'color': '#c8c8d8',
        'font-style': 'italic',
        'font-weight': '400',
        'border-width': '1px',
        'border-color': '#8a8aa6',
        'border-style': 'dashed',
        'height': '24px',
      }},
    }},
    {{
      selector: 'node:selected',
      style: {{
        'border-width': '3px',
        'border-color': '#ffffff',
        'border-opacity': 0.9,
      }},
    }},
    {{
      selector: 'node.dimmed',
      style: {{
        'opacity': 0.15,
      }},
    }},
    {{
      selector: 'node.highlighted',
      style: {{
        'border-width': '2px',
        'border-color': '#ffcc00',
        'opacity': 1,
      }},
    }},
    {{
      selector: 'edge',
      style: {{
        'width': 2.5,
        'line-color': '#7878b8',
        'target-arrow-color': '#7878b8',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        'opacity': 0.85,
        'arrow-scale': 1.1,
      }},
    }},
    {{
      selector: 'edge.possible',
      style: {{
        'line-style': 'dashed',
        'line-dash-pattern': [5, 3],
        'opacity': 0.5,
        'line-color': '#9090b8',
        'target-arrow-color': '#9090b8',
      }},
    }},
    {{
      selector: 'edge.external',
      style: {{
        'line-style': 'dotted',
        'opacity': 0.45,
        'line-color': '#7070a0',
        'target-arrow-color': '#7070a0',
        'width': 1.5,
      }},
    }},
    {{
      selector: 'edge.dimmed',
      style: {{ 'opacity': 0.04 }},
    }},
    {{
      selector: 'edge:selected, edge.highlighted',
      style: {{
        'line-color': '#ffcc00',
        'target-arrow-color': '#ffcc00',
        'opacity': 1,
        'width': 3.5,
      }},
    }},
  ],
  minZoom: 0.02,
  maxZoom: 8,
  wheelSensitivity: 0.3,
}});

// ── Layout ────────────────────────────────────────────────────────────────
function applyLayout(name) {{
  let opts;
  if (name === 'dagre-lr') {{
    opts = {{ name: 'dagre', rankDir: 'LR', nodeSep: 40, edgeSep: 10, rankSep: 120, animate: true, animationDuration: 300 }};
  }} else if (name === 'dagre-tb') {{
    opts = {{ name: 'dagre', rankDir: 'TB', nodeSep: 40, edgeSep: 10, rankSep: 100, animate: true, animationDuration: 300 }};
  }} else if (name === 'cose') {{
    opts = {{ name: 'cose', animate: true, animationDuration: 500, nodeRepulsion: 8000, idealEdgeLength: 100, gravity: 0.5 }};
  }} else if (name === 'concentric') {{
    opts = {{ name: 'concentric', animate: true, animationDuration: 300, concentric: n => n.degree(), levelWidth: () => 2 }};
  }}
  cy.layout(opts).run();
}}

applyLayout('dagre-lr');

// ── Callers / Callees index ───────────────────────────────────────────────
const calleeMap = {{}};  // nodeId → [nodeId]
const callerMap = {{}};  // nodeId → [nodeId]
GRAPH_DATA.nodes.forEach(n => {{ calleeMap[n.id] = []; callerMap[n.id] = []; }});
GRAPH_DATA.edges.forEach(e => {{
  if (calleeMap[e.source]) calleeMap[e.source].push(e.target);
  if (callerMap[e.target]) callerMap[e.target].push(e.source);
}});
const nodeById = {{}};
GRAPH_DATA.nodes.forEach(n => {{ nodeById[n.id] = n; }});

// ── Info panel ────────────────────────────────────────────────────────────
const panel = document.getElementById('panel');
const panelTitle = document.getElementById('panel-title');
const panelMeta = document.getElementById('panel-meta');
const sourceCode = document.getElementById('source-code');
const calleesSection = document.getElementById('callees-section');
const callersSection = document.getElementById('callers-section');

function showPanel(data) {{
  panel.classList.add('open');
  panelTitle.textContent = data.qualified_name || data.name;
  panelTitle.title = data.qualified_name || data.name;

  const isExternal = data.language === 'external';
  const badge = `<span class="lang-badge" style="background:${{data.color}}">${{data.language}}</span>`;
  const file = data.relative_file || data.file;
  const lines = `L${{data.start_line}}–${{data.end_line}}`;

  panelMeta.innerHTML = isExternal
    ? `
    <div class="info-row"><span class="info-label">Lang</span><span class="info-val">${{badge}}</span></div>
    <div class="info-row"><span class="info-label">Kind</span><span class="info-val">External / stdlib / builtin (no definition in this project)</span></div>
  `
    : `
    <div class="info-row"><span class="info-label">Lang</span><span class="info-val">${{badge}}</span></div>
    <div class="info-row"><span class="info-label">File</span><span class="info-val" title="${{data.file}}">${{file}}</span></div>
    <div class="info-row"><span class="info-label">Lines</span><span class="info-val">${{lines}}</span></div>
    ${{data.class_name ? `<div class="info-row"><span class="info-label">Class</span><span class="info-val">${{data.class_name}}</span></div>` : ''}}
  `;

  // External nodes have no source; hide the source block entirely for them.
  document.getElementById('source-wrap').style.display = isExternal ? 'none' : '';
  sourceCode.textContent = data.source_code || '';

  // Callees
  const calleeIds = [...new Set(calleeMap[data.id] || [])];
  calleesSection.innerHTML = calleeIds.length
    ? `<div class="section-title">Calls (${{calleeIds.length}})</div>` +
      calleeIds.map(tid => {{
        const t = nodeById[tid];
        return t ? `<span class="fn-link" data-id="${{tid}}" title="${{t.relative_file || t.file}}: ${{t.qualified_name}}">${{t.qualified_name}}</span>` : '';
      }}).join('')
    : '';

  // Callers
  const callerIds = [...new Set(callerMap[data.id] || [])];
  callersSection.innerHTML = callerIds.length
    ? `<div class="section-title">Called by (${{callerIds.length}})</div>` +
      callerIds.map(sid => {{
        const s = nodeById[sid];
        return s ? `<span class="fn-link" data-id="${{sid}}" title="${{s.relative_file || s.file}}: ${{s.qualified_name}}">${{s.qualified_name}}</span>` : '';
      }}).join('')
    : '';

  document.getElementById('stat-selection').textContent =
    `Selected: ${{data.qualified_name}}`;
}}

function closePanel() {{
  panel.classList.remove('open');
  document.getElementById('stat-selection').textContent = '';
  cy.elements().unselect();
}}

document.getElementById('panel-close').addEventListener('click', closePanel);

panel.addEventListener('click', e => {{
  const link = e.target.closest('.fn-link');
  if (link) {{
    const id = link.dataset.id;
    const ele = cy.$(`#${{CSS.escape(id)}}`);
    if (ele.length) {{
      cy.animate({{ fit: {{ eles: ele, padding: 80 }} }}, {{ duration: 300 }});
      ele.select();
      showPanel(ele.data());
    }}
  }}
}});

cy.on('tap', 'node', evt => {{
  showPanel(evt.target.data());
}});

cy.on('tap', evt => {{
  if (evt.target === cy) closePanel();
}});

// ── Controls ──────────────────────────────────────────────────────────────
document.getElementById('btn-fit').addEventListener('click', () => cy.fit(undefined, 40));
document.getElementById('btn-zoom-in').addEventListener('click', () => cy.zoom({{ level: cy.zoom() * 1.3, renderedPosition: {{ x: cy.width()/2, y: cy.height()/2 }} }}));
document.getElementById('btn-zoom-out').addEventListener('click', () => cy.zoom({{ level: cy.zoom() / 1.3, renderedPosition: {{ x: cy.width()/2, y: cy.height()/2 }} }}));

document.getElementById('layout-select').addEventListener('change', e => applyLayout(e.target.value));

let showPossible = true;
document.getElementById('btn-possible').addEventListener('click', function() {{
  showPossible = !showPossible;
  this.classList.toggle('active', showPossible);
  cy.edges('.possible').style('display', showPossible ? 'element' : 'none');
}});

// Toggle external (stdlib/builtin/third-party) nodes and their edges, then
// re-run the current layout so the graph re-flows around what's left.
let showExternal = true;
document.getElementById('btn-external').addEventListener('click', function() {{
  showExternal = !showExternal;
  this.classList.toggle('active', showExternal);
  const disp = showExternal ? 'element' : 'none';
  cy.nodes('.external').style('display', disp);
  cy.edges('.external').style('display', disp);
  applyLayout(document.getElementById('layout-select').value);
}});

// ── Fuzzy search ──────────────────────────────────────────────────────────
const searchIndex = GRAPH_DATA.nodes.map(n => n);
const fuse = new Fuse(searchIndex, {{
  keys: ['name', 'qualified_name', 'relative_file', 'class_name'],
  threshold: 0.35,
  ignoreLocation: true,
  minMatchCharLength: 2,
}});

const searchInput = document.getElementById('search');
const searchResults = document.getElementById('search-results');
const searchCount = document.getElementById('search-count');

searchInput.addEventListener('input', function() {{
  const q = this.value.trim();
  if (!q) {{
    cy.elements().removeClass('dimmed highlighted');
    searchResults.classList.remove('visible');
    searchCount.textContent = '';
    return;
  }}

  const results = fuse.search(q, {{ limit: 50 }});
  const matchIds = new Set(results.map(r => r.item.id));
  searchCount.textContent = matchIds.size || '';

  cy.batch(() => {{
    cy.nodes().forEach(n => {{
      if (matchIds.has(n.id())) {{
        n.removeClass('dimmed').addClass('highlighted');
      }} else {{
        n.addClass('dimmed').removeClass('highlighted');
      }}
    }});
    cy.edges().forEach(e => {{
      const bothMatch = matchIds.has(e.source().id()) && matchIds.has(e.target().id());
      e.toggleClass('dimmed', !bothMatch);
    }});
  }});

  // Show dropdown
  if (results.length > 0) {{
    searchResults.innerHTML = results.slice(0, 20).map(r => {{
      const n = r.item;
      return `<div class="sr-item" data-id="${{n.id}}">
        <span class="sr-name">${{n.qualified_name}}</span>
        <span class="sr-file">${{n.relative_file || n.file}}</span>
      </div>`;
    }}).join('');
    searchResults.classList.add('visible');
  }} else {{
    searchResults.classList.remove('visible');
  }}
}});

searchResults.addEventListener('click', e => {{
  const item = e.target.closest('.sr-item');
  if (!item) return;
  const id = item.dataset.id;
  const ele = cy.$(`#${{CSS.escape(id)}}`);
  if (ele.length) {{
    cy.animate({{ fit: {{ eles: ele.neighborhood().add(ele), padding: 80 }} }}, {{ duration: 300 }});
    ele.select();
    showPanel(ele.data());
  }}
  searchResults.classList.remove('visible');
  searchInput.value = '';
  cy.elements().removeClass('dimmed highlighted');
  searchCount.textContent = '';
}});

document.addEventListener('click', e => {{
  if (!document.getElementById('search-wrap').contains(e.target)) {{
    searchResults.classList.remove('visible');
  }}
}});

// ── Keyboard shortcuts ────────────────────────────────────────────────────
document.addEventListener('keydown', e => {{
  if (e.key === 'Escape') {{
    closePanel();
    searchInput.value = '';
    cy.elements().removeClass('dimmed highlighted');
    searchCount.textContent = '';
    searchResults.classList.remove('visible');
  }}
  if ((e.ctrlKey || e.metaKey) && e.key === 'f') {{
    e.preventDefault();
    searchInput.focus();
  }}
  if (e.key === '0' && (e.ctrlKey || e.metaKey)) {{
    e.preventDefault();
    cy.fit(undefined, 40);
  }}
}});

// ── Status bar ────────────────────────────────────────────────────────────
const files = new Set(
  GRAPH_DATA.nodes.filter(n => n.language !== 'external' && n.file).map(n => n.file)
);
const defCount = GRAPH_DATA.nodes.filter(n => n.language !== 'external').length;
const extCount = GRAPH_DATA.nodes.length - defCount;
document.getElementById('stat-nodes').textContent =
  `${{defCount}} function${{defCount !== 1 ? 's' : ''}}` +
  (extCount ? ` + ${{extCount}} external` : '');
document.getElementById('stat-edges').textContent =
  `${{GRAPH_DATA.edges.length}} edge${{GRAPH_DATA.edges.length !== 1 ? 's' : ''}}`;
document.getElementById('stat-files').textContent =
  `${{files.size}} file${{files.size !== 1 ? 's' : ''}}`;
</script>

<script>
{flow_script}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Flowchart ("block scheme") view — CSS + JS injected via plain placeholders so
# we don't have to brace-escape this code for str.format().
# ---------------------------------------------------------------------------

FLOW_STYLE = """
#main { position: relative; }
#flow-view {
  position: absolute; inset: 0; display: none; flex-direction: column;
  background: #1a1a2e; z-index: 20;
}
#flow-view.open { display: flex; }
#flow-bar {
  display: flex; align-items: center; gap: 10px;
  padding: 6px 12px; background: #252526; border-bottom: 1px solid #3c3c3c;
  flex-shrink: 0;
}
#flow-title { font-weight: 600; font-size: 13px; color: #dcdcaa; }
#flow-hint { font-size: 11px; color: #888; }
#flow-cy {
  flex: 1;
  background: #1a1a2e;
  background-image: radial-gradient(circle, #2a2a40 1px, transparent 1px);
  background-size: 28px 28px;
}
"""

FLOW_SCRIPT = r"""
(function () {
  const flowView  = document.getElementById('flow-view');
  const flowTitle = document.getElementById('flow-title');
  const btnFlow   = document.getElementById('btn-flow');
  let flowCy = null;
  let uid = 0;
  const nid = () => 'f' + (uid++);

  // ── Convert a structured flow tree into Cytoscape elements ────────────────
  // Each builder returns {entry, exits:[{id,label,cls}]}. Open exits are wired
  // to whatever statement follows, so branches merge without extra junctions.
  function buildElements(flow) {
    const nodes = [], edges = [];
    const addN = (id, label, cls, extra) =>
      nodes.push({ data: Object.assign({ id, label: label || '' }, extra || {}), classes: cls });
    const addE = (s, t, label, cls) => {
      if (!s || !t) return;
      edges.push({ data: { id: nid(), source: s, target: t, label: label || '' }, classes: cls || 'flow-edge' });
    };

    const entry = nid(); addN(entry, '▶ start', 'flow-entry');
    const exit  = nid(); addN(exit,  '■ end',   'flow-exit');
    const ctx0  = { loopCont: null, loopBreak: null, funcExit: exit };

    function seq(stmts, ctx) {
      let e = null, pend = [];
      (stmts || []).forEach(s => {
        const r = stmt(s, ctx);
        if (!r) return;
        if (e === null) e = r.entry;
        pend.forEach(p => addE(p.id, r.entry, p.label, p.cls));
        pend = r.exits;
      });
      return { entry: e, exits: pend };
    }

    function stmt(s, ctx) {
      const t = s.t;
      if (t === 'process') {
        const id = nid(); addN(id, s.lines.join('\n'), 'flow-process');
        return { entry: id, exits: [{ id }] };
      }
      if (t === 'jump') {
        const id = nid(); addN(id, s.label, 'flow-jump flow-' + s.kind);
        if (s.kind === 'return' || s.kind === 'throw') addE(id, ctx.funcExit, '', 'flow-edge');
        else if (s.kind === 'break')    addE(id, ctx.loopBreak || ctx.funcExit, 'break', 'flow-jumpedge');
        else if (s.kind === 'continue') addE(id, ctx.loopCont  || ctx.funcExit, 'continue', 'flow-jumpedge');
        return { entry: id, exits: [] };
      }
      if (t === 'if') {
        const d = nid(); addN(d, s.cond || '?', 'flow-decision');
        const exits = [];
        const tb = seq(s.then, ctx);
        if (tb.entry) { addE(d, tb.entry, 'yes', 'flow-yes'); tb.exits.forEach(x => exits.push(x)); }
        else exits.push({ id: d, label: 'yes', cls: 'flow-yes' });
        const eb = seq(s.else, ctx);
        if (eb.entry) { addE(d, eb.entry, 'no', 'flow-no'); eb.exits.forEach(x => exits.push(x)); }
        else exits.push({ id: d, label: 'no', cls: 'flow-no' });
        return { entry: d, exits };
      }
      if (t === 'loop') {
        const h = nid();     addN(h, s.label || 'loop', 'flow-loop');
        const le = nid();    addN(le, '', 'flow-connector');
        const ctx2 = Object.assign({}, ctx, { loopCont: h, loopBreak: le });
        const body = seq(s.body, ctx2);
        if (s.do) {
          const start = body.entry || h;
          body.exits.forEach(x => addE(x.id, h, x.label, x.cls));
          addE(h, body.entry || le, 'repeat', 'flow-yes flow-loopback');
          addE(h, le, 'done', 'flow-no');
          return { entry: start, exits: [{ id: le }] };
        }
        if (body.entry) {
          addE(h, body.entry, 'loop', 'flow-yes');
          body.exits.forEach(x => addE(x.id, h, '', 'flow-loopback'));
        } else {
          addE(h, h, '', 'flow-loopback');
        }
        addE(h, le, 'done', 'flow-no');
        return { entry: h, exits: [{ id: le }] };
      }
      if (t === 'switch') {
        const d  = nid(); addN(d, 'switch ' + (s.label || ''), 'flow-decision flow-switch');
        const se = nid(); addN(se, '', 'flow-connector');
        const ctx2 = Object.assign({}, ctx, { loopBreak: se });
        let hasDefault = false;
        (s.cases || []).forEach(c => {
          if (/default|case _/i.test(c.label)) hasDefault = true;
          const cb = seq(c.body, ctx2);
          if (cb.entry) { addE(d, cb.entry, c.label, 'flow-case'); cb.exits.forEach(x => addE(x.id, se, x.label, x.cls)); }
          else addE(d, se, c.label, 'flow-case');
        });
        if (!hasDefault) addE(d, se, 'default', 'flow-case');
        return { entry: d, exits: [{ id: se }] };
      }
      if (t === 'try') {
        const tn = nid(); addN(tn, 'try', 'flow-try');
        const tm = nid(); addN(tm, '', 'flow-connector');
        const body = seq(s.body, ctx);
        if (body.entry) { addE(tn, body.entry, '', 'flow-edge'); body.exits.forEach(x => addE(x.id, tm, x.label, x.cls)); }
        else addE(tn, tm, '', 'flow-edge');
        (s.handlers || []).forEach(h => {
          const hb = seq(h.body, ctx);
          if (hb.entry) { addE(tn, hb.entry, h.label, 'flow-catch'); hb.exits.forEach(x => addE(x.id, tm, x.label, x.cls)); }
          else addE(tn, tm, h.label, 'flow-catch');
        });
        let exits = [{ id: tm }];
        if (s.final && s.final.length) {
          const fb = seq(s.final, ctx);
          if (fb.entry) { addE(tm, fb.entry, 'finally', 'flow-edge'); exits = fb.exits; }
        }
        return { entry: tn, exits };
      }
      const id = nid(); addN(id, t, 'flow-process');
      return { entry: id, exits: [{ id }] };
    }

    const top = seq(flow, ctx0);
    if (top.entry) { addE(entry, top.entry, '', 'flow-edge'); top.exits.forEach(x => addE(x.id, exit, x.label, x.cls)); }
    else addE(entry, exit, '', 'flow-edge');

    // Prune nodes unreachable from entry (e.g. dead code after an exhaustive
    // switch/return) so the chart shows only the live flow — no floating nodes.
    const adj = {};
    edges.forEach(e => { (adj[e.data.source] = adj[e.data.source] || []).push(e.data.target); });
    const seen = new Set([entry]); const stack = [entry];
    while (stack.length) {
      const n = stack.pop();
      (adj[n] || []).forEach(m => { if (!seen.has(m)) { seen.add(m); stack.push(m); } });
    }
    return {
      nodes: nodes.filter(n => seen.has(n.data.id)),
      edges: edges.filter(e => seen.has(e.data.source) && seen.has(e.data.target)),
    };
  }

  const FLOW_CY_STYLE = [
    { selector: 'node', style: {
        'label': 'data(label)', 'color': '#1e1e1e', 'font-size': '10px',
        'font-family': 'Consolas, monospace', 'text-valign': 'center', 'text-halign': 'center',
        'text-wrap': 'wrap', 'text-max-width': '200px', 'width': 'label', 'height': 'label',
        'padding': '8px', 'background-color': '#9cdcfe', 'shape': 'round-rectangle' } },
    { selector: '.flow-process',  style: { 'background-color': '#9cdcfe', 'shape': 'round-rectangle' } },
    { selector: '.flow-decision', style: { 'background-color': '#dcdcaa', 'shape': 'diamond', 'text-max-width': '140px', 'padding': '14px' } },
    { selector: '.flow-loop',     style: { 'background-color': '#c586c0', 'shape': 'hexagon', 'padding': '12px' } },
    { selector: '.flow-entry',    style: { 'background-color': '#4ec9b0', 'shape': 'round-pentagon', 'color': '#10231f', 'font-weight': '700' } },
    { selector: '.flow-exit',     style: { 'background-color': '#f48771', 'shape': 'round-rectangle', 'color': '#2a0f0a', 'font-weight': '700' } },
    { selector: '.flow-jump',     style: { 'background-color': '#ce9178', 'shape': 'round-rectangle' } },
    { selector: '.flow-return',   style: { 'background-color': '#f48771' } },
    { selector: '.flow-throw',    style: { 'background-color': '#f44747', 'color': '#fff' } },
    { selector: '.flow-break',    style: { 'background-color': '#d7ba7d' } },
    { selector: '.flow-continue', style: { 'background-color': '#d7ba7d' } },
    { selector: '.flow-try',      style: { 'background-color': '#608b4e', 'color': '#fff' } },
    { selector: '.flow-connector',style: { 'width': '12px', 'height': '12px', 'background-color': '#7878b8', 'label': '' } },
    { selector: 'edge', style: {
        'width': 2, 'line-color': '#7878b8', 'target-arrow-color': '#7878b8',
        'target-arrow-shape': 'triangle', 'curve-style': 'bezier', 'label': 'data(label)',
        'font-size': '9px', 'color': '#cfcfe6', 'text-background-color': '#1a1a2e',
        'text-background-opacity': 1, 'text-background-padding': '2px' } },
    { selector: '.flow-yes', style: { 'line-color': '#4ec9b0', 'target-arrow-color': '#4ec9b0', 'color': '#7fe0cd' } },
    { selector: '.flow-no',  style: { 'line-color': '#f48771', 'target-arrow-color': '#f48771', 'color': '#f4a791' } },
    { selector: '.flow-loopback', style: {
        'line-style': 'dashed', 'line-color': '#c586c0', 'target-arrow-color': '#c586c0',
        'curve-style': 'unbundled-bezier', 'control-point-distances': [-60], 'control-point-weights': [0.5] } },
    { selector: '.flow-case',  style: { 'color': '#dcdcaa' } },
    { selector: '.flow-catch', style: { 'line-style': 'dashed', 'line-color': '#f44747', 'target-arrow-color': '#f44747', 'color': '#f48a8a' } },
    { selector: '.flow-jumpedge', style: { 'line-style': 'dashed' } },
  ];

  function openFlow(data) {
    if (!data || !data.flow || !data.flow.length) return;
    uid = 0;
    const els = buildElements(data.flow);
    flowTitle.textContent = (data.qualified_name || data.name) + '()';
    flowView.classList.add('open');
    if (flowCy) { flowCy.destroy(); flowCy = null; }
    flowCy = cytoscape({
      container: document.getElementById('flow-cy'),
      elements: els, style: FLOW_CY_STYLE,
      minZoom: 0.05, maxZoom: 4, wheelSensitivity: 0.3,
    });
    flowCy.layout({ name: 'dagre', rankDir: 'TB', nodeSep: 28, rankSep: 48, edgeSep: 12 }).run();
    flowCy.fit(undefined, 30);
  }
  function closeFlow() { flowView.classList.remove('open'); }

  // ── Wiring ────────────────────────────────────────────────────────────────
  function refreshBtn() {
    const sel = cy.$('node:selected');
    const ok = sel.length === 1 && sel.data('language') !== 'external'
      && Array.isArray(sel.data('flow')) && sel.data('flow').length;
    btnFlow.style.display = ok ? 'block' : 'none';
  }
  cy.on('select unselect', 'node', refreshBtn);
  btnFlow.addEventListener('click', () => {
    const sel = cy.$('node:selected');
    if (sel.length) openFlow(sel.data());
  });
  document.getElementById('flow-back').addEventListener('click', closeFlow);
  document.getElementById('flow-fit').addEventListener('click', () => { if (flowCy) flowCy.fit(undefined, 30); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && flowView.classList.contains('open')) { e.stopPropagation(); closeFlow(); } }, true);
})();
"""


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def render(graph: CallGraph, title: str) -> str:
    """Render a CallGraph to a fully self-contained HTML string."""
    js_bundle, is_inline = get_js_bundle()
    if not is_inline:
        print(
            "\n  " + "!" * 68 + "\n"
            "  [WARNING] Could not inline JS libraries; falling back to CDN tags.\n"
            "  The output file is NOT self-contained and REQUIRES internet access\n"
            "  to open. Re-run with a network connection to embed the libraries.\n"
            "  " + "!" * 68
        )

    nodes_data = [
        {
            "id": n.id,
            "name": n.name,
            "qualified_name": n.qualified_name,
            "file": n.file,
            "relative_file": n.relative_file,
            "class_name": n.class_name,
            "start_line": n.start_line,
            "end_line": n.end_line,
            "source_code": n.source_code,
            "language": n.language,
            "color": n.color,
            "flow": n.flow or [],
        }
        for n in graph.nodes
    ]

    edges_data = [
        {
            "id": e.id,
            "source": e.source,
            "target": e.target,
            "confidence": e.confidence,
        }
        for e in graph.edges
    ]

    graph_data_json = json.dumps(
        {"nodes": nodes_data, "edges": edges_data},
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")

    return HTML_TEMPLATE.format(
        title=html.escape(title, quote=True),
        js_bundle=js_bundle,
        graph_data=graph_data_json,
        flow_style=FLOW_STYLE,
        flow_script=FLOW_SCRIPT,
    )
