"""Generate a fully self-contained HTML call-graph visualization."""

from __future__ import annotations

import json
import urllib.request
import os
import hashlib
from pathlib import Path
from typing import Optional

from .graph_builder import CallGraph, GraphNode, GraphEdge

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


def _fetch_lib(name: str, url: str) -> Optional[str]:
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
</div>

<div id="main">
  <div id="cy"></div>

  <div id="panel">
    <div id="panel-header">
      <span id="panel-title"></span>
      <span id="panel-close" title="Close">✕</span>
    </div>
    <div id="panel-body">
      <div id="panel-meta"></div>
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
        'text-wrap': 'none',
        'text-overflow-wrap': 'ellipsis',
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
        'width': 1.5,
        'line-color': '#4a4a6a',
        'target-arrow-color': '#4a4a6a',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        'opacity': 0.7,
        'arrow-scale': 0.9,
      }},
    }},
    {{
      selector: 'edge.possible',
      style: {{
        'line-style': 'dashed',
        'line-dash-pattern': [5, 3],
        'opacity': 0.35,
        'line-color': '#6a6a8a',
        'target-arrow-color': '#6a6a8a',
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
        'width': 2.5,
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

  const badge = `<span class="lang-badge" style="background:${{data.color}}">${{data.language}}</span>`;
  const file = data.relative_file || data.file;
  const lines = `L${{data.start_line}}–${{data.end_line}}`;

  panelMeta.innerHTML = `
    <div class="info-row"><span class="info-label">Lang</span><span class="info-val">${{badge}}</span></div>
    <div class="info-row"><span class="info-label">File</span><span class="info-val" title="${{data.file}}">${{file}}</span></div>
    <div class="info-row"><span class="info-label">Lines</span><span class="info-val">${{lines}}</span></div>
    ${{data.class_name ? `<div class="info-row"><span class="info-label">Class</span><span class="info-val">${{data.class_name}}</span></div>` : ''}}
  `;

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
const files = new Set(GRAPH_DATA.nodes.map(n => n.file));
document.getElementById('stat-nodes').textContent =
  `${{GRAPH_DATA.nodes.length}} function${{GRAPH_DATA.nodes.length !== 1 ? 's' : ''}}`;
document.getElementById('stat-edges').textContent =
  `${{GRAPH_DATA.edges.length}} edge${{GRAPH_DATA.edges.length !== 1 ? 's' : ''}}`;
document.getElementById('stat-files').textContent =
  `${{files.size}} file${{files.size !== 1 ? 's' : ''}}`;
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def render(graph: CallGraph, title: str) -> str:
    """Render a CallGraph to a fully self-contained HTML string."""
    js_bundle, is_inline = get_js_bundle()
    if not is_inline:
        print("  [warn] Using CDN script tags – output may not be fully offline-capable.")

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
    )

    return HTML_TEMPLATE.format(
        title=title,
        js_bundle=js_bundle,
        graph_data=graph_data_json,
    )
