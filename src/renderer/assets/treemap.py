"""File / module tree-map view assets.

A second tab that collapses the call graph to the file level and renders it
as a nested squarified treemap. Injected via @@TREEMAPSTYLE@@ / @@TREEMAPSCRIPT@@.
"""

TREEMAP_STYLE = """
#treemap {
  flex: 1;
  display: none;
  position: relative;
  background: #1a1a2e;
  overflow: hidden;
}
#treemap.open { display: block; }
#treemap-bar {
  position: absolute; top: 0; left: 0; right: 0; height: 30px;
  display: flex; align-items: center; gap: 8px;
  padding: 0 12px;
  background: rgba(37, 37, 38, .92);
  border-bottom: 1px solid #3c3c3c;
  font-size: 12px; z-index: 5;
}
#treemap-crumbs { color: #888; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#treemap-crumbs .crumb { color: #9cdcfe; cursor: pointer; }
#treemap-crumbs .crumb:last-child { color: #dcdcaa; cursor: default; }
#treemap-crumbs .crumb:not(:last-child):hover { text-decoration: underline; }
#treemap-hint { font-size: 11px; color: #888; white-space: nowrap; }
#treemap-canvas { position: absolute; top: 30px; left: 0; right: 0; bottom: 0; }
.tm-svg { width: 100%; height: 100%; display: block; touch-action: none; }
.tm-label { font-weight: 600; pointer-events: none; }
.tm-leaf, .tm-container { cursor: pointer; }
.tm-node.tm-hover > rect { stroke: #ffcc00 !important; stroke-width: 2px !important; stroke-opacity: 1 !important; }
"""

# Built entirely via DOM (createElementNS / innerHTML strings) like the rest of
# the engine. Relies on globals defined by APP_SCRIPT: GRAPH_DATA, plus the
# shared #panel DOM. Injected verbatim — must not contain the token "@@".
TREEMAP_SCRIPT = r"""
(function () {
  const G        = GRAPH_DATA;
  const tmEl     = document.getElementById('treemap');
  const canvas   = document.getElementById('treemap-canvas');
  const crumbsEl = document.getElementById('treemap-crumbs');
  const tabs     = document.querySelectorAll('.tb-tab');
  const graphOnly = document.querySelectorAll('[data-graph-only]');
  const SVGNS = 'http://www.w3.org/2000/svg';

  const PAD = 2, HEADER = 18, MINS = 10, MINLABEL = 48;

  let fileMap = null;     // path -> file aggregate
  let nodeByPath = null;  // path -> tree node (first/shallowest occurrence)
  let drillStack = [];    // tree nodes; last is the current root being shown
  let built = false;

  function el(tag, attrs) {
    const e = document.createElementNS(SVGNS, tag);
    if (attrs) for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function clip(name, w) {
    const max = Math.floor((w - 10) / 6.2);
    if (max < 1) return '';
    return name.length > max ? name.slice(0, Math.max(1, max - 1)) + '…' : name;
  }

  // ── Aggregate the function-level graph to files ───────────────────────────
  function aggregate() {
    fileMap = new Map();
    const fileOf = {};   // function id -> file path
    const getF = (path, lang, color) => {
      let f = fileMap.get(path);
      if (!f) {
        f = { path, name: path.split('/').pop(), lang, color,
              funcs: [], callsOut: new Set(), callsIn: new Set() };
        fileMap.set(path, f);
      }
      return f;
    };
    G.nodes.forEach((n) => {
      if (n.language === 'external' || !n.file) return;
      const path = n.relative_file || n.file;
      getF(path, n.language, n.color).funcs.push(n);
      fileOf[n.id] = path;
    });
    G.edges.forEach((e) => {
      const sp = fileOf[e.source], tp = fileOf[e.target];
      if (!sp || !tp || sp === tp) return;
      fileMap.get(sp).callsOut.add(tp);
      fileMap.get(tp).callsIn.add(sp);
    });
  }

  // ── Build the containment tree (each file placed once, at first discovery) ─
  function buildTree() {
    aggregate();
    nodeByPath = new Map();
    const files = [...fileMap.values()];
    const visited = new Set();

    function makeNode(f) {
      visited.add(f.path);
      const node = {
        file: f, name: f.name, path: f.path, lang: f.lang, color: f.color,
        selfWeight: Math.max(1, f.funcs.length), children: [],
      };
      nodeByPath.set(f.path, node);
      [...f.callsOut].sort().forEach((tp) => {
        if (!visited.has(tp)) node.children.push(makeNode(fileMap.get(tp)));
      });
      return node;
    }

    // Entry-point files (nothing calls them) are roots. If everything is in a
    // cycle, fall back to using every file as a root.
    let roots = files.filter((f) => f.callsIn.size === 0);
    if (!roots.length) roots = files.slice();
    roots.sort((a, b) => b.callsOut.size - a.callsOut.size || a.path.localeCompare(b.path));

    const top = [];
    roots.forEach((f) => { if (!visited.has(f.path)) top.push(makeNode(f)); });
    // Stragglers reachable only through cross-links that were already claimed.
    files.forEach((f) => { if (!visited.has(f.path)) top.push(makeNode(f)); });

    const title = (document.getElementById('title').textContent || 'project')
      .replace('📊', '').trim();
    const virtual = { name: title, path: null, virtual: true, color: '#5a5a72',
                      lang: '', selfWeight: 0, children: top };
    (function weigh(n) {
      let w = n.selfWeight;
      n.children.forEach((c) => { w += weigh(c); });
      return (n.weight = w);
    })(virtual);
    return virtual;
  }

  // ── Squarified treemap layout (sets .x/.y/.w/.h on each cell) ──────────────
  function squarify(cells, x, y, w, h) {
    const total = cells.reduce((s, c) => s + c.weight, 0);
    if (total <= 0 || w <= 0 || h <= 0) { cells.forEach((c) => { c.w = c.h = 0; }); return; }
    const A = w * h;
    cells.forEach((c) => { c._a = c.weight / total * A; });
    let cx = x, cy = y, cw = w, ch = h, i = 0;
    const worst = (row, side) => {
      const s = row.reduce((a, c) => a + c._a, 0);
      let mx = -Infinity, mn = Infinity;
      row.forEach((c) => { if (c._a > mx) mx = c._a; if (c._a < mn) mn = c._a; });
      const ss = side * side, s2 = s * s;
      return Math.max(ss * mx / s2, s2 / (ss * mn));
    };
    while (i < cells.length) {
      const side = Math.min(cw, ch);
      const row = [cells[i]];
      let end = i + 1;
      while (end < cells.length &&
             worst(row.concat(cells[end]), side) <= worst(row, side)) {
        row.push(cells[end]); end++;
      }
      const sum = row.reduce((a, c) => a + c._a, 0);
      if (cw <= ch) {
        const rh = sum / cw || 0; let px = cx;
        row.forEach((c) => { const ww = c._a / (rh || 1); c.x = px; c.y = cy; c.w = ww; c.h = rh; px += ww; });
        cy += rh; ch -= rh;
      } else {
        const rw = sum / ch || 0; let py = cy;
        row.forEach((c) => { const hh = c._a / (rw || 1); c.x = cx; c.y = py; c.w = rw; c.h = hh; py += hh; });
        cx += rw; cw -= rw;
      }
      i = end;
    }
  }

  // ── Render a tree node (and recurse) into the SVG ─────────────────────────
  function renderNode(n, x, y, w, h, parent) {
    const hasKids = n.children && n.children.length;
    const fill = n.color || '#5a5a72';
    const g = el('g', { class: 'tm-node ' + (hasKids ? 'tm-container' : 'tm-leaf') });
    if (!n.virtual) g.setAttribute('data-file', n.path);
    g.__node = n;
    parent.appendChild(g);

    const tip = el('title');
    tip.textContent = n.virtual ? n.name
      : n.name + ' — ' + n.file.funcs.length + ' function(s), calls '
        + n.file.callsOut.size + ' file(s)';
    g.appendChild(tip);

    if (!hasKids) {
      g.appendChild(el('rect', { x, y, width: w, height: h, rx: 3,
        fill, 'fill-opacity': 0.85, stroke: '#1a1a2e' }));
      if (w > MINLABEL && h > 16) {
        const t = el('text', { class: 'tm-label', x: x + 5, y: y + 14,
          'font-size': 11, fill: '#10231f' });
        t.textContent = clip(n.name, w);
        g.appendChild(t);
      }
      return;
    }

    g.appendChild(el('rect', { x, y, width: w, height: h, rx: 3,
      fill, 'fill-opacity': 0.10, stroke: fill, 'stroke-opacity': 0.5 }));
    const showHeader = !n.virtual && h > HEADER + 6 && w > MINLABEL;
    if (showHeader) {
      const t = el('text', { class: 'tm-label', x: x + 5, y: y + 13, 'font-size': 11, fill });
      t.textContent = clip(n.name, w);
      g.appendChild(t);
    }
    const hh = showHeader ? HEADER : 2;
    const ix = x + PAD, iy = y + hh, iw = w - 2 * PAD, ih = h - hh - PAD;
    if (iw < MINS || ih < MINS) return;

    const cells = n.children.map((c) => ({ weight: c.weight, node: c }));
    if (!n.virtual && n.selfWeight > 0) cells.push({ weight: n.selfWeight, self: true });
    cells.sort((a, b) => b.weight - a.weight);
    squarify(cells, ix, iy, iw, ih);
    cells.forEach((c) => {
      if (c.w <= 0.5 || c.h <= 0.5) return;
      if (c.self) {
        g.appendChild(el('rect', { x: c.x, y: c.y, width: c.w, height: c.h, rx: 2,
          fill, 'fill-opacity': 0.85, stroke: '#1a1a2e' }));
      } else {
        renderNode(c.node, c.x, c.y, c.w, c.h, g);
      }
    });
  }

  function current() { return drillStack[drillStack.length - 1]; }

  function draw() {
    const w = canvas.clientWidth || 800, h = canvas.clientHeight || 600;
    canvas.innerHTML = '';
    const svg = el('svg', { class: 'tm-svg' });
    canvas.appendChild(svg);
    renderNode(current(), 0, 0, w, h, svg);
    drawCrumbs();
  }

  function drawCrumbs() {
    crumbsEl.innerHTML = '';
    drillStack.forEach((n, i) => {
      if (i > 0) {
        const sep = document.createElement('span');
        sep.textContent = ' › ';
        crumbsEl.appendChild(sep);
      }
      const c = document.createElement('span');
      c.className = 'crumb';
      c.textContent = n.virtual ? 'all files' : n.name;
      c.dataset.idx = i;
      crumbsEl.appendChild(c);
    });
  }

  // ── Side panel (reuses the shared #panel) ─────────────────────────────────
  function langBadge(lang, color) {
    return '<span class="lang-badge" style="background:' + color + '">' + esc(lang || '?') + '</span>';
  }
  function showFilePanel(node) {
    if (!node || node.virtual) return;
    const f = node.file;
    const calls = [...f.callsOut].sort(), callers = [...f.callsIn].sort();
    document.getElementById('panel').classList.add('open');
    const pt = document.getElementById('panel-title');
    pt.textContent = node.path; pt.title = node.path;
    document.getElementById('panel-meta').innerHTML =
      '<div class="info-row"><span class="info-label">Lang</span><span class="info-val">' + langBadge(node.lang, node.color) + '</span></div>'
      + '<div class="info-row"><span class="info-label">File</span><span class="info-val" title="' + esc(f.path) + '">' + esc(node.path) + '</span></div>'
      + '<div class="info-row"><span class="info-label">Funcs</span><span class="info-val">' + f.funcs.length + '</span></div>';
    document.getElementById('source-wrap').style.display = 'none';
    document.getElementById('btn-flow').style.display = 'none';

    const fnList = f.funcs.length
      ? '<div class="section-title">Functions (' + f.funcs.length + ')</div>'
        + f.funcs.map((fn) => '<span class="fn-link tm-fn" data-id="' + esc(fn.id) + '" title="' + esc(fn.qualified_name) + '">' + esc(fn.qualified_name) + '</span>').join('')
      : '';
    const callList = calls.length
      ? '<div class="section-title">Calls files (' + calls.length + ')</div>'
        + calls.map((p) => '<span class="fn-link tm-filelink" data-file="' + esc(p) + '">' + esc(p) + '</span>').join('')
      : '';
    const callerList = callers.length
      ? '<div class="section-title">Called by files (' + callers.length + ')</div>'
        + callers.map((p) => '<span class="fn-link tm-filelink" data-file="' + esc(p) + '">' + esc(p) + '</span>').join('')
      : '';
    document.getElementById('callees-section').innerHTML = fnList + callList;
    document.getElementById('callers-section').innerHTML = callerList;
    document.getElementById('stat-selection').textContent = 'File: ' + node.path;
  }

  // ── Interaction ───────────────────────────────────────────────────────────
  let hoverG = null;
  function setHover(g) {
    if (hoverG === g) return;
    if (hoverG) hoverG.classList.remove('tm-hover');
    hoverG = g;
    if (hoverG) hoverG.classList.add('tm-hover');
  }
  canvas.addEventListener('pointermove', (e) => {
    const g = e.target.closest ? e.target.closest('[data-file]') : null;
    setHover(g);
  });
  canvas.addEventListener('pointerleave', () => setHover(null));
  canvas.addEventListener('click', (e) => {
    const g = e.target.closest('[data-file]');
    if (g && g.__node) showFilePanel(g.__node);
  });
  canvas.addEventListener('dblclick', (e) => {
    const g = e.target.closest('[data-file]');
    const n = g && g.__node;
    if (!n || !(n.children && n.children.length) || current() === n) return;
    drillStack.push(n);
    draw();
  });
  crumbsEl.addEventListener('click', (e) => {
    const c = e.target.closest('.crumb');
    if (!c) return;
    const idx = +c.dataset.idx;
    if (idx === drillStack.length - 1) return;
    drillStack = drillStack.slice(0, idx + 1);
    draw();
  });

  // Panel links specific to the tree-map view. (Function links also carry the
  // shared .fn-link class, so APP_SCRIPT's handler selects the graph node and
  // swaps the panel to it — we just need to bring the call-graph tab forward.)
  document.getElementById('panel').addEventListener('click', (e) => {
    const fl = e.target.closest('.tm-filelink');
    if (fl) {
      e.stopPropagation();
      const n = nodeByPath && nodeByPath.get(fl.dataset.file);
      if (n) showFilePanel(n);
      return;
    }
    if (e.target.closest('.tm-fn') && tmEl.classList.contains('open')) switchView('graph');
  });

  // ── Tab switching ─────────────────────────────────────────────────────────
  function switchView(view) {
    const isTree = view === 'treemap';
    document.getElementById('cy').style.display = isTree ? 'none' : '';
    tmEl.classList.toggle('open', isTree);
    tabs.forEach((t) => t.classList.toggle('active', t.dataset.view === view));
    graphOnly.forEach((n) => { n.style.display = isTree ? 'none' : ''; });
    if (isTree) {
      if (!built) { drillStack = [buildTree()]; built = true; }
      draw();
    }
  }
  tabs.forEach((t) => t.addEventListener('click', () => switchView(t.dataset.view)));
  window.switchView = switchView;

  window.addEventListener('resize', () => { if (tmEl.classList.contains('open')) draw(); });
})();
"""
