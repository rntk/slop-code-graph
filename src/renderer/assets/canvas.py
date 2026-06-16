"""Canvas view asset: a topic-aligned reading canvas for the LLM flow split.

Vanilla JS embedded into the self-contained HTML (mirrors the shape of
treemap.py: a CANVAS_STYLE string + a CANVAS_SCRIPT IIFE injected via
@@CANVASSTYLE@@ / @@CANVASSCRIPT@@). It consumes ``GRAPH_DATA.canvas`` (see
src/canvas/CONTRACT.md) and reproduces the layout/UX of the reference
components ext/src/components/CanvasTopicHierarchyRail.jsx and
ext/src/components/CanvasSummaryView.jsx, re-themed for the dark IDE look:

  ┌────────────┬───────────────────────┬───────────────┐
  │ topic rail │  middle content       │  side card    │
  │ (columns   │  (code  | summaries)  │ (summary |    │
  │  by level) │                       │  source code) │
  └────────────┴───────────────────────┴───────────────┘

Topic cards are absolutely positioned and vertically aligned to the content
they describe (measured line / summary-card offsets), in columns by hierarchy
level. A level switcher collapses depth; a mode toggle swaps the middle column
between the source code and the per-topic summaries. The opposite-side floating
card shows the active topic's summary (code mode) or its original source lines
(summary mode).
"""

CANVAS_STYLE = """
#canvas-view {
  flex: 1;
  display: none;
  min-height: 0;
  flex-direction: column;
  background: #1e1e1e;
  color: #d4d4d4;
  overflow: hidden;
}
#canvas-view.open { display: flex; }

/* ── Canvas toolbar (level switch + mode toggle) ─────────────────────────── */
#canvas-bar {
  display: flex; align-items: center; gap: 12px;
  padding: 6px 12px; flex-shrink: 0;
  background: #252526; border-bottom: 1px solid #3c3c3c;
}
#canvas-bar .cv-label { font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: .08em; }
.cv-levels { display: inline-flex; gap: 4px; }
.cv-level-btn {
  padding: 3px 9px; background: #3c3c3c; border: 1px solid #555; border-radius: 4px;
  color: #d4d4d4; font-size: 12px; cursor: pointer;
}
.cv-level-btn:hover { background: #4a4a4a; border-color: #777; }
.cv-level-btn.active { background: #007acc; border-color: #007acc; color: #fff; }
#canvas-mode-toggle {
  padding: 4px 12px; background: #3c3c3c; border: 1px solid #555; border-radius: 4px;
  color: #d4d4d4; font-size: 12px; cursor: pointer; white-space: nowrap;
}
#canvas-mode-toggle:hover { background: #4a4a4a; border-color: #777; }
#canvas-mode-toggle.is-summary { background: #094771; border-color: #007acc; }
#canvas-bar .cv-spacer { flex: 1; }
#canvas-bar .cv-hint { font-size: 11px; color: #777; }

/* ── Scroll area + positioned stage ─────────────────────────────────────── */
#canvas-scroll {
  flex: 1; min-height: 0; overflow: auto; position: relative;
  background:
    radial-gradient(circle, #2a2a40 1px, transparent 1px);
  background-size: 28px 28px;
}
#canvas-stage { position: relative; }

/* ── Left topic rail: cards are absolutely positioned & level-columned ───── */
.cv-card {
  position: absolute;
  box-sizing: border-box;
  width: var(--cv-card-w, 200px);
  display: flex; flex-direction: column; justify-content: center; gap: 3px;
  padding: 8px 10px 8px 12px;
  background: #252526;
  border: 1px solid #3c3c3c;
  border-left: 4px solid var(--cv-accent, #007acc);
  color: #d4d4d4; cursor: pointer; text-align: left; overflow: hidden;
  transition: border-color .15s ease, background .15s ease;
}
.cv-card:hover, .cv-card.is-active, .cv-card.is-selected {
  background: #2d2d40;
  border: 1px solid #6a6a8e;
  border-left: 4px solid var(--cv-accent, #007acc);
}
.cv-card.is-selected { border-color: #ffffff; }
.cv-card--root { background: #2a2a32; }
.cv-card-name {
  display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-clamp: 2;
  overflow: hidden; font-size: 12px; font-weight: 700; line-height: 1.2; color: #e8eaf4;
}
.cv-card-meta {
  font-size: 10px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: #888;
}

/* ── Middle content: code column ────────────────────────────────────────── */
#canvas-code-col { position: absolute; top: 0; }
#canvas-code {
  margin: 0; padding: 12px 14px;
  font-family: 'Consolas', 'Courier New', monospace; font-size: 12px; line-height: 1.5;
  background: #1a1a1f; border: 1px solid #3c3c3c; border-radius: 6px;
  color: #d4d4d4; white-space: pre; tab-size: 4;
}
.cv-line { display: block; padding: 0 6px; border-radius: 2px; }
.cv-line.is-header { color: #6a9955; font-weight: 700; background: rgba(106,153,85,.07); }
.cv-line.is-hl { background: rgba(0,122,204,.20); box-shadow: inset 3px 0 0 var(--cv-accent, #007acc); }
.cv-line.is-hl-dim { background: rgba(0,122,204,.08); }

/* ── Middle content: summary cards column (summary mode) ─────────────────── */
#canvas-summary-col { position: absolute; top: 0; }
.cv-sum-card {
  box-sizing: border-box;
  margin: 0 0 10px 0; padding: 12px 14px;
  background: #252526; border: 1px solid #3c3c3c; border-left: 4px solid var(--cv-accent, #007acc);
  border-radius: 4px; cursor: pointer; transition: border-color .15s ease, background .15s ease;
}
.cv-sum-card:hover, .cv-sum-card.is-active { background: #2d2d40; border-color: #6a6a8e; border-left-color: var(--cv-accent, #007acc); }
.cv-sum-kicker { font-size: 10px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: #888; }
.cv-sum-path { display: block; margin: 2px 0 6px; font-size: 13px; font-weight: 600; color: #9cdcfe; word-break: break-word; }
.cv-sum-text { font-size: 13px; line-height: 1.5; color: #d4d4d4; white-space: pre-wrap; }
.cv-sum-text.is-empty { color: #777; font-style: italic; }
.cv-sum-meta { margin-top: 8px; font-size: 10px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: #777; }

/* ── Right floating side card (summary in code mode / source in summary) ── */
#canvas-side-col { position: absolute; top: 0; }
.cv-side-card {
  position: absolute; box-sizing: border-box;
  width: var(--cv-side-w, 320px);
  background: #1d1d24; border: 1px solid #565676; border-left: 4px solid var(--cv-accent, #007acc);
  border-radius: 6px; box-shadow: 0 8px 24px rgba(0,0,0,.5); overflow: hidden;
  display: flex; flex-direction: column;
}
.cv-side-head { padding: 8px 12px; border-bottom: 1px solid #3c3c3c; }
.cv-side-kicker { font-size: 10px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: #888; }
.cv-side-path { display: block; margin-top: 2px; font-size: 12px; font-weight: 600; color: #9cdcfe; word-break: break-word; }
.cv-side-body { padding: 10px 12px; overflow: auto; max-height: 60vh; }
.cv-side-body .cv-sum-text { font-size: 13px; }
.cv-side-body pre {
  margin: 0; font-family: 'Consolas','Courier New',monospace; font-size: 11px; line-height: 1.5;
  white-space: pre; color: #d4d4d4;
}
.cv-side-body pre .is-header { color: #6a9955; font-weight: 700; }

#canvas-empty { padding: 28px; color: #888; font-style: italic; }
"""

CANVAS_SCRIPT = r"""
(function () {
  var G = (typeof GRAPH_DATA !== 'undefined') ? GRAPH_DATA : null;
  var DATA = G && G.canvas;
  var esc = (typeof escapeHtml !== 'undefined')
    ? escapeHtml
    : function (s) { s = (s == null ? '' : String(s)); return s
        .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
        .replace(/"/g,'&quot;').replace(/'/g,'&#39;'); };

  // ── Layout constants (mirror topicCards.js, re-scaled for the dark theme) ──
  var RAIL_PADDING = 16, CARD_W = 200, COL_GAP = 14, CARD_MIN_H = 56, CARD_GAP = 8;
  var CODE_W = 760, SIDE_W = 340, COL_PAD = 18, STAGE_PAD_TOP = 16;

  // ── State ──────────────────────────────────────────────────────────────
  var built = false, summaryMode = false, selectedLevel = 0, maxLevel = 0;
  var activePath = null, selectedPath = null;
  var topics = [], lines = [], lineMeta = [];
  var lineEls = [];            // span per source line (code mode)
  var sumCardEls = {};         // leaf path -> summary card element (summary mode)

  // ── Topic-path helpers (port of splitTopicPath / color utils) ────────────
  function splitPath(name) {
    return String(name || '').split('>').map(function (p) { return p.trim(); }).filter(Boolean);
  }
  function hashStr(v) { var h = 0, s = String(v || ''); for (var i = 0; i < s.length; i++) { h = (h << 5) - h + s.charCodeAt(i); h |= 0; } return Math.abs(h); }
  function accentColor(rootName, depth) {
    var hue = hashStr(rootName) % 360;
    var sat = Math.max(30, 60 - depth * 6);
    var lig = Math.min(64, 42 + depth * 6);
    return 'hsl(' + hue + ',' + sat + '%,' + lig + '%)';
  }

  // ── Hierarchy tree from topic paths (parents aggregate descendant units) ──
  // Each tree node: { path, name, depth, units:Set<1-based>, children:Map }
  function buildTree() {
    var root = { path: '', name: 'root', depth: -1, units: new Set(), children: new Map() };
    var byPath = new Map();
    byPath.set('', root);
    topics.forEach(function (t) {
      var parts = splitPath(t.path);
      var units = Array.isArray(t.lineNumbers) ? t.lineNumbers : [];
      var cur = root;
      for (var i = 0; i < parts.length; i++) {
        var full = parts.slice(0, i + 1).join(' > ');
        if (!cur.children.has(parts[i])) {
          var node = { path: full, name: parts[i], depth: i, units: new Set(), children: new Map() };
          cur.children.set(parts[i], node);
          byPath.set(full, node);
        }
        cur = cur.children.get(parts[i]);
        units.forEach(function (u) { cur.units.add(u); });
      }
    });
    // Roll child units up into ancestors.
    (function agg(n) { n.children.forEach(function (c) { agg(c); c.units.forEach(function (u) { n.units.add(u); }); }); })(root);
    return { root: root, byPath: byPath };
  }

  function nodesUpToLevel(root, level) {
    var out = [];
    (function walk(n) {
      if (n.depth >= 0 && n.depth <= level) out.push(n);
      if (n.depth < level) n.children.forEach(walk);
    })(root);
    return out;
  }

  // ── Measurement: unit (1-based) -> {top, bottom} in stage coordinates ─────
  function measureCodeMetrics() {
    var m = new Map();
    // Line spans' offsetParent is #canvas-code-col (the nearest positioned
    // ancestor); the column's own offsetTop (within #canvas-stage) closes the
    // gap to stage coordinates.
    var col = document.getElementById('canvas-code-col');
    var base = col ? col.offsetTop : 0;
    for (var i = 0; i < lineEls.length; i++) {
      var el = lineEls[i];
      if (!el) continue;
      m.set(i + 1, { top: base + el.offsetTop, bottom: base + el.offsetTop + el.offsetHeight });
    }
    return m;
  }

  // ── Card layout: position each node by its measured units, columns by level
  function layoutCards(metrics) {
    var nodes = nodesUpToLevel(tree.root, selectedLevel);
    var cards = nodes.map(function (n) {
      var units = Array.from(n.units).sort(function (a, b) { return a - b; });
      var tops = [], bots = [];
      units.forEach(function (u) { var mm = metrics.get(u); if (mm) { tops.push(mm.top); bots.push(mm.bottom); } });
      var top = tops.length ? Math.min.apply(null, tops) : STAGE_PAD_TOP;
      var bottom = bots.length ? Math.max.apply(null, bots) : top + CARD_MIN_H;
      return {
        path: n.path, name: n.name, depth: n.depth,
        rootName: splitPath(n.path)[0] || n.name,
        unitCount: n.units.size,
        startUnit: units.length ? units[0] : 0,
        top: top, height: Math.max(CARD_MIN_H, bottom - top),
      };
    });
    return resolveColumnOverlaps(cards);
  }

  // Port of resolveColumnOverlaps: within a level column, stack with no overlap.
  function resolveColumnOverlaps(cards) {
    var byLevel = new Map();
    cards.forEach(function (c) { (byLevel.get(c.depth) || byLevel.set(c.depth, []).get(c.depth)).push(c); });
    byLevel.forEach(function (group) {
      group.sort(function (a, b) { return a.startUnit - b.startUnit || a.top - b.top || a.path.localeCompare(b.path); });
      var prevBottom = -Infinity;
      group.forEach(function (c, i) {
        var top = Math.max(c.top, prevBottom + CARD_GAP);
        var bottom = Math.max(top + c.height, top + CARD_MIN_H);
        var next = group[i + 1];
        if (next && next.top - CARD_GAP >= top + CARD_MIN_H) bottom = Math.min(bottom, next.top - CARD_GAP);
        c.top = top; c.height = bottom - top; prevBottom = bottom;
      });
    });
    return cards;
  }

  // ── Renderers ────────────────────────────────────────────────────────────
  function railWidth() { return RAIL_PADDING * 2 + (selectedLevel + 1) * CARD_W + selectedLevel * COL_GAP; }

  function renderRail(cards) {
    var rail = document.getElementById('canvas-rail');
    rail.innerHTML = '';
    cards.forEach(function (c) {
      var el = document.createElement('div');
      el.className = 'cv-card' + (c.depth === 0 ? ' cv-card--root' : '')
        + (activePath === c.path ? ' is-active' : '') + (selectedPath === c.path ? ' is-selected' : '');
      el.style.left = (RAIL_PADDING + c.depth * (CARD_W + COL_GAP)) + 'px';
      el.style.top = c.top + 'px';
      el.style.height = c.height + 'px';
      el.style.setProperty('--cv-card-w', CARD_W + 'px');
      el.style.setProperty('--cv-accent', accentColor(c.rootName, c.depth));
      el.setAttribute('data-path', c.path);
      var name = document.createElement('span'); name.className = 'cv-card-name'; name.textContent = c.name;
      var meta = document.createElement('span'); meta.className = 'cv-card-meta'; meta.textContent = c.unitCount + ' lines';
      el.appendChild(name); el.appendChild(meta);
      bindCard(el, c.path);
      rail.appendChild(el);
    });
  }

  function renderCode() {
    var col = document.getElementById('canvas-code-col');
    col.style.display = ''; col.style.left = (railWidth() + COL_PAD) + 'px'; col.style.width = CODE_W + 'px';
    var pre = document.getElementById('canvas-code');
    pre.innerHTML = '';
    lineEls = [];
    lines.forEach(function (ln, i) {
      var span = document.createElement('span');
      span.className = 'cv-line' + (lineMeta[i] && lineMeta[i].kind === 'header' ? ' is-header' : '');
      span.textContent = ln.length ? ln : ' ';
      pre.appendChild(span);
      lineEls.push(span);
    });
    document.getElementById('canvas-summary-col').style.display = 'none';
  }

  // The "frontier" of the tree at the selected level: each branch contributes
  // the node at exactly selectedLevel, or its leaf if the branch is shorter.
  // These are the nodes the summary column shows — one card per visible branch,
  // mirroring the rail's deepest visible column.
  function frontierNodes() {
    var out = [];
    (function walk(n) {
      if (n.depth >= 0 && (n.depth === selectedLevel || n.children.size === 0)) { out.push(n); return; }
      n.children.forEach(walk);
    })(tree.root);
    return out.sort(function (a, b) {
      var au = Math.min.apply(null, Array.from(a.units)) || 0;
      var bu = Math.min.apply(null, Array.from(b.units)) || 0;
      return au - bu || a.path.localeCompare(b.path);
    });
  }

  // Concatenate the summaries of a node's descendant leaf topics (deferred the
  // hierarchical parent-merge LLM pass, so a parent's text is its leaves joined).
  function aggregateSummary(node) {
    if (node.children.size === 0) return summaryForPath(node.path);
    var parts = [];
    topics.forEach(function (t) {
      var p = t.path;
      if ((p === node.path || p.indexOf(node.path + ' > ') === 0) && t.summary) {
        parts.push('• ' + t.summary);
      }
    });
    return parts.join('\n');
  }

  function renderSummaries() {
    var col = document.getElementById('canvas-summary-col');
    col.style.display = ''; col.style.left = (railWidth() + COL_PAD) + 'px'; col.style.width = CODE_W + 'px';
    col.innerHTML = '';
    sumCardEls = {};
    frontierNodes().forEach(function (node) {
      var p = node.path;
      var sumText = aggregateSummary(node);
      var card = document.createElement('div');
      card.className = 'cv-sum-card' + (activePath === p ? ' is-active' : '');
      card.style.setProperty('--cv-accent', accentColor(splitPath(p)[0] || p, node.depth));
      card.setAttribute('data-path', p);
      var kick = document.createElement('div'); kick.className = 'cv-sum-kicker'; kick.textContent = 'Summary';
      var path = document.createElement('span'); path.className = 'cv-sum-path'; path.textContent = p;
      var text = document.createElement('div');
      text.className = 'cv-sum-text' + (sumText ? '' : ' is-empty');
      text.textContent = sumText || 'No summary for this section.';
      var meta = document.createElement('div'); meta.className = 'cv-sum-meta';
      var units = Array.from(node.units).sort(function (a, b) { return a - b; });
      meta.textContent = units.length ? ('lines ' + units[0] + '–' + units[units.length - 1] + ' (' + units.length + ')') : '';
      card.appendChild(kick); card.appendChild(path); card.appendChild(text); if (meta.textContent) card.appendChild(meta);
      bindSummaryCard(card, p);
      col.appendChild(card);
      sumCardEls[p] = card;
    });
    document.getElementById('canvas-code-col').style.display = 'none';
  }

  // In summary mode, position rail cards from measured summary-card rects.
  function measureSummaryMetrics() {
    // Returns node.path -> {top, bottom}; leaves from their own card, parents aggregate.
    var leafRect = {};
    var col = document.getElementById('canvas-summary-col');
    var base = col ? col.offsetTop : 0;
    Object.keys(sumCardEls).forEach(function (p) {
      var el = sumCardEls[p];
      leafRect[p] = { top: base + el.offsetTop, bottom: base + el.offsetTop + el.offsetHeight };
    });
    return leafRect;
  }

  function layoutCardsSummary() {
    var leafRect = measureSummaryMetrics();
    var nodes = nodesUpToLevel(tree.root, selectedLevel);
    var cards = nodes.map(function (n) {
      var tops = [], bots = [];
      Object.keys(leafRect).forEach(function (p) {
        if (p === n.path || p.indexOf(n.path + ' > ') === 0 || n.path.indexOf(p + ' > ') === 0) {
          tops.push(leafRect[p].top); bots.push(leafRect[p].bottom);
        }
      });
      var top = tops.length ? Math.min.apply(null, tops) : STAGE_PAD_TOP;
      var bottom = bots.length ? Math.max.apply(null, bots) : top + CARD_MIN_H;
      return {
        path: n.path, name: n.name, depth: n.depth, rootName: splitPath(n.path)[0] || n.name,
        unitCount: n.units.size, startUnit: Array.from(n.units).sort(function (a, b) { return a - b; })[0] || 0,
        top: top, height: Math.max(CARD_MIN_H, bottom - top),
      };
    });
    return resolveColumnOverlaps(cards);
  }

  // ── Side card (right): summary (code mode) or source code (summary mode) ──
  function renderSideCard(cardTopMap) {
    var col = document.getElementById('canvas-side-col');
    col.innerHTML = '';
    col.style.left = (railWidth() + COL_PAD + CODE_W + COL_PAD) + 'px';
    if (!activePath) return;
    var node = tree.byPath.get(activePath);
    if (!node) return;
    var accent = accentColor(splitPath(activePath)[0] || activePath, node.depth);
    var topPx = (cardTopMap && cardTopMap[activePath] != null) ? cardTopMap[activePath] : STAGE_PAD_TOP;

    var card = document.createElement('div');
    card.className = 'cv-side-card';
    card.style.top = topPx + 'px';
    card.style.setProperty('--cv-side-w', SIDE_W + 'px');
    card.style.setProperty('--cv-accent', accent);
    var head = document.createElement('div'); head.className = 'cv-side-head';
    var kick = document.createElement('div'); kick.className = 'cv-side-kicker';
    var path = document.createElement('span'); path.className = 'cv-side-path'; path.textContent = activePath;
    var body = document.createElement('div'); body.className = 'cv-side-body';

    if (summaryMode) {
      // Floating card with the ORIGINAL source lines for this topic.
      kick.textContent = 'Source';
      var units = Array.from(node.units).sort(function (a, b) { return a - b; });
      var pre = document.createElement('pre');
      units.forEach(function (u) {
        var idx = u - 1; var ln = lines[idx] != null ? lines[idx] : '';
        var s = document.createElement('span');
        if (lineMeta[idx] && lineMeta[idx].kind === 'header') s.className = 'is-header';
        s.textContent = (ln.length ? ln : ' ') + '\n';
        pre.appendChild(s);
      });
      body.appendChild(pre);
    } else {
      // Floating summary card for this topic (use the matching leaf summary).
      kick.textContent = 'Summary';
      var sumText = summaryForPath(activePath);
      var text = document.createElement('div');
      text.className = 'cv-sum-text' + (sumText ? '' : ' is-empty');
      text.textContent = sumText || 'No summary for this section.';
      body.appendChild(text);
    }
    head.appendChild(kick); head.appendChild(path);
    card.appendChild(head); card.appendChild(body);
    col.appendChild(card);
  }

  function summaryForPath(path) {
    // Exact topic, else the first descendant leaf topic that carries a summary.
    var exact = topics.find(function (t) { return splitPath(t.path).join(' > ') === path; });
    if (exact && exact.summary) return exact.summary;
    var desc = topics.filter(function (t) { var p = splitPath(t.path).join(' > '); return p === path || p.indexOf(path + ' > ') === 0; });
    var withText = desc.find(function (t) { return t.summary; });
    return withText ? withText.summary : (exact ? exact.summary : '');
  }

  // ── Highlight active topic in the code column ─────────────────────────────
  function applyHighlight() {
    if (summaryMode) return;
    var hlUnits = new Set();
    if (activePath) {
      var node = tree.byPath.get(activePath);
      if (node) node.units.forEach(function (u) { hlUnits.add(u); });
    }
    for (var i = 0; i < lineEls.length; i++) {
      var on = hlUnits.has(i + 1);
      lineEls[i].classList.toggle('is-hl', on);
    }
  }

  // ── Interaction ──────────────────────────────────────────────────────────
  function setActive(path) {
    activePath = path;
    refreshActiveClasses();
    applyHighlight();
    renderSideCard(lastCardTops);
    scrollToActive();
  }
  function refreshActiveClasses() {
    var rail = document.getElementById('canvas-rail');
    Array.prototype.forEach.call(rail.querySelectorAll('.cv-card'), function (el) {
      var p = el.getAttribute('data-path');
      el.classList.toggle('is-active', p === activePath);
      el.classList.toggle('is-selected', p === selectedPath);
    });
    Object.keys(sumCardEls).forEach(function (p) {
      sumCardEls[p].classList.toggle('is-active', p === activePath);
    });
  }
  function scrollToActive() {
    if (!activePath) return;
    var top = lastCardTops && lastCardTops[activePath];
    if (top == null) return;
    var scroll = document.getElementById('canvas-scroll');
    if (top < scroll.scrollTop + 40 || top > scroll.scrollTop + scroll.clientHeight - 80) {
      scroll.scrollTo({ top: Math.max(0, top - 80), behavior: 'smooth' });
    }
  }
  function bindCard(el, path) {
    el.addEventListener('mouseenter', function () { if (!selectedPath) setActive(path); });
    el.addEventListener('mouseleave', function () { if (!selectedPath) setActive(null); });
    el.addEventListener('click', function () {
      if (selectedPath === path) { selectedPath = null; setActive(null); }
      else { selectedPath = path; setActive(path); }
    });
  }
  function bindSummaryCard(el, path) {
    el.addEventListener('mouseenter', function () { if (!selectedPath) setActive(path); });
    el.addEventListener('mouseleave', function () { if (!selectedPath) setActive(null); });
    el.addEventListener('click', function () {
      if (selectedPath === path) { selectedPath = null; setActive(null); }
      else { selectedPath = path; setActive(path); }
    });
  }

  // ── Full (re)layout pass ──────────────────────────────────────────────────
  var tree = null, lastCardTops = {};
  function relayout() {
    var stage = document.getElementById('canvas-stage');
    stage.style.minWidth = (railWidth() + COL_PAD + CODE_W + COL_PAD + SIDE_W + COL_PAD) + 'px';

    if (summaryMode) renderSummaries(); else renderCode();

    // Measure after the content column has laid out, then position rail/side.
    requestAnimationFrame(function () {
      var cards = summaryMode ? layoutCardsSummary() : layoutCards(measureCodeMetrics());
      lastCardTops = {};
      cards.forEach(function (c) { lastCardTops[c.path] = c.top; });
      renderRail(cards);
      renderSideCard(lastCardTops);
      applyHighlight();
      // Stage height = tallest column.
      var contentCol = document.getElementById(summaryMode ? 'canvas-summary-col' : 'canvas-code-col');
      var railH = cards.reduce(function (m, c) { return Math.max(m, c.top + c.height); }, 0);
      var contentH = contentCol ? contentCol.offsetTop + contentCol.offsetHeight : 0;
      stage.style.height = (Math.max(railH, contentH) + STAGE_PAD_TOP + 40) + 'px';
    });
  }

  function renderLevels() {
    var wrap = document.getElementById('canvas-levels');
    wrap.innerHTML = '';
    for (var l = 0; l <= maxLevel; l++) {
      (function (level) {
        var b = document.createElement('button');
        b.className = 'cv-level-btn' + (level === selectedLevel ? ' active' : '');
        b.textContent = 'L' + level;
        b.addEventListener('click', function () {
          if (level === selectedLevel) return;
          selectedLevel = level; selectedPath = null; activePath = null;
          renderLevels(); relayout();
        });
        wrap.appendChild(b);
      })(l);
    }
  }

  // ── DOM scaffold (created once into #canvas-view) ─────────────────────────
  function scaffold(container) {
    container.innerHTML =
      '<div id="canvas-bar">'
      + '<span class="cv-label">Level</span><span id="canvas-levels" class="cv-levels"></span>'
      + '<button id="canvas-mode-toggle">Show summaries</button>'
      + '<span class="cv-spacer"></span>'
      + '<span class="cv-hint">hover a topic to align &amp; highlight · click to pin</span>'
      + '</div>'
      + '<div id="canvas-scroll"><div id="canvas-stage">'
      + '<div id="canvas-rail"></div>'
      + '<div id="canvas-code-col"><pre id="canvas-code"></pre></div>'
      + '<div id="canvas-summary-col"></div>'
      + '<div id="canvas-side-col"></div>'
      + '</div></div>';
    document.getElementById('canvas-mode-toggle').addEventListener('click', function () {
      summaryMode = !summaryMode;
      selectedPath = null; activePath = null;
      this.classList.toggle('is-summary', summaryMode);
      this.textContent = summaryMode ? 'Show code' : 'Show summaries';
      relayout();
    });
    window.addEventListener('resize', function () { if (built) relayout(); });
  }

  function build() {
    if (built) return;
    if (!DATA || !DATA.lines || !DATA.lines.length || !Array.isArray(DATA.topics) || !DATA.topics.length) return;
    var container = document.getElementById('canvas-view');
    if (!container) return;

    lines = DATA.lines; lineMeta = DATA.lineMeta || [];
    topics = DATA.topics.map(function (t) {
      return {
        path: splitPath(t.path).join(' > '),
        level: t.level || splitPath(t.path).length,
        lineNumbers: Array.isArray(t.lineNumbers) ? t.lineNumbers : [],
        summary: t.summary || '',
      };
    });
    maxLevel = topics.reduce(function (m, t) { return Math.max(m, t.level - 1); }, 0);
    selectedLevel = maxLevel;

    scaffold(container);
    tree = buildTree();
    renderLevels();
    relayout();
    built = true;
  }

  // Exposed for the tab switcher to call lazily on first activation. Idempotent.
  window.__buildCanvas = build;
})();
"""
