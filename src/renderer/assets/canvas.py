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
/* When canvas is the active view, the info panel sibling must not reserve
   layout space (its box would otherwise sit on the right, producing empty
   unused area even while visually translated away). */
#canvas-view.open ~ #panel { display: none !important; }

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
  flex: 1; min-height: 0; overflow: hidden; position: relative;
  background-color: #1e1e1e;
  background-image: radial-gradient(circle, #2a2a40 1px, transparent 1px);
  background-size: calc(28px * var(--canvas-scale, 1)) calc(28px * var(--canvas-scale, 1));
  background-position: var(--canvas-translate-x, 40px) var(--canvas-translate-y, 40px);
  user-select: none;
  cursor: grab;
}
#canvas-scroll.is-dragging {
  cursor: grabbing !important;
}
body.canvas-global-dragging,
body.canvas-global-dragging * {
  cursor: grabbing !important;
}
#canvas-stage {
  position: absolute;
  transform-origin: 0 0;
  transform: translate(var(--canvas-translate-x, 40px), var(--canvas-translate-y, 40px)) scale(var(--canvas-scale, 1));
}
#canvas-stage.is-focusing-highlight {
  transition: transform 320ms ease;
}

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

.cv-card-content {
  display: flex;
  flex-direction: column;
  gap: 3px;

  --_lh: var(--topic-card-label-height, 50px);
  --_p: 6px;
  --_vis-top: max(
    0px,
    calc(-1 * var(--canvas-translate-y) / var(--canvas-scale) - var(--topic-card-top))
  );
  --_vis-bot: min(
    var(--topic-card-height),
    calc(
      (var(--canvas-area-height, 100px) - var(--canvas-translate-y)) / var(--canvas-scale) -
        var(--topic-card-top)
    )
  );
  --_vis-center: calc((var(--_vis-top) + var(--_vis-bot)) / 2);
  --_offset: clamp(
    calc(var(--_lh) / 2 + var(--_p) - var(--topic-card-height) / 2),
    calc(var(--_vis-center) - var(--topic-card-height) / 2),
    calc(var(--topic-card-height) / 2 - var(--_lh) / 2 - var(--_p))
  );

  transform: translateY(var(--_offset));
}

.cv-card-name {
  display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: var(--topic-card-title-line-clamp, 2); line-clamp: var(--topic-card-title-line-clamp, 2);
  overflow: hidden; font-size: var(--topic-card-title-font-size, 12px); font-weight: 700; line-height: 1.2; color: #e8eaf4;
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
  --cv-side-kicker-size: 10px;
  --cv-side-path-size: 12px;
  --cv-side-text-size: 13px;
  --cv-side-code-size: 11px;
}
.cv-side-head { padding: 8px 12px; border-bottom: 1px solid #3c3c3c; }
.cv-side-kicker { font-size: var(--cv-side-kicker-size); font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: #888; }
.cv-side-path { display: block; margin-top: 2px; font-size: var(--cv-side-path-size); font-weight: 600; color: #9cdcfe; word-break: break-word; }
.cv-side-body { padding: 10px 12px; overflow: auto; max-height: 60vh; }
.cv-side-body .cv-sum-text { font-size: var(--cv-side-text-size); }
.cv-side-body pre {
  margin: 0; font-family: 'Consolas','Courier New',monospace; font-size: var(--cv-side-code-size); line-height: 1.5;
  white-space: pre; color: #d4d4d4;
}
.cv-side-body pre .is-header { color: #6a9955; font-weight: 700; }

#canvas-empty { padding: 28px; color: #888; font-style: italic; }

/* ── Zoom controls (floating) ───────────────────────────────────────────── */
.canvas-controls {
  position: absolute;
  bottom: 20px;
  right: 20px;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  z-index: 10;
}
.canvas-controls.is-horizontal {
  flex-direction: row;
  align-items: flex-end;
}
.canvas-controls-header {
  display: flex;
  flex-direction: row-reverse;
  gap: 4px;
}
.canvas-controls.is-horizontal .canvas-controls-header {
  flex-direction: column;
}
.canvas-controls-body {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}
.canvas-controls.is-horizontal .canvas-controls-body {
  flex-direction: row;
  align-items: flex-end;
}
.canvas-controls.is-folded .canvas-controls-body {
  display: none;
}
.canvas-zoom-btn {
  width: 32px;
  height: 32px;
  background: rgba(37, 37, 38, 0.85);
  backdrop-filter: blur(14px);
  border: 1px solid #3c3c3c;
  border-radius: 4px;
  font-size: 16px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ccc;
  transition: background 0.15s, color 0.15s;
}
.canvas-zoom-btn:hover {
  background: #007acc;
  color: #fff;
  border-color: #007acc;
}
.canvas-spacer {
  height: 4px;
}
.canvas-controls.is-horizontal .canvas-spacer {
  width: 4px;
  height: auto;
}
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

  // ── Zoom/Pan State ──────────────────────────────────────────────────────
  var scale = 1.0, translateX = 40, translateY = 40;
  var isDragging = false;
  var lastMouseX = 0, lastMouseY = 0;
  var userMoved = false;

  // ── Ported Dense Card Collision and Layout Resolution ───────────────────
  function cardsOverlapVertically(topCard, bottomCard) {
    return (
      topCard.top + topCard.height + CARD_GAP > bottomCard.top &&
      bottomCard.top + bottomCard.height + CARD_GAP > topCard.top
    );
  }

  function getCompactCardHeight(card, isCrowded) {
    var height = card.height || CARD_MIN_H;
    if (!isCrowded || height > 96) return height;
    return Math.max(CARD_MIN_H, height - 16);
  }

  function nudgeCrowdedPair(topCard, bottomCard) {
    var overlap = topCard.top + topCard.height + CARD_GAP - bottomCard.top;
    if (overlap <= 0) return;

    var remaining = overlap;
    var topMin = Math.max(0, topCard.originalTop - 18);
    var bottomMax = bottomCard.originalTop + 18;

    var topMove = Math.min(remaining / 2, Math.max(0, topCard.top - topMin));
    topCard.top -= topMove;
    remaining -= topMove;

    var bottomMove = Math.min(remaining, Math.max(0, bottomMax - bottomCard.top));
    bottomCard.top += bottomMove;
  }

  function getDenseCardZIndex(card, isCrowded) {
    if (!isCrowded) return 1;
    return 20 + Math.max(0, 10 - Math.min(card.unitCount || 0, 10));
  }

  function adjustCrowdedLevelCards(levelCards) {
    var sortedCards = levelCards.slice().sort(function (left, right) {
      return left.top - right.top || left.startUnit - right.startUnit || left.path.localeCompare(right.path);
    });

    var workingCards = sortedCards.map(function (card, index) {
      var previousCard = sortedCards[index - 1];
      var nextCard = sortedCards[index + 1];
      var isCrowded =
        (previousCard && cardsOverlapVertically(previousCard, card)) ||
        (nextCard && cardsOverlapVertically(card, nextCard));
      var height = getCompactCardHeight(card, isCrowded);

      return {
        path: card.path,
        visualKey: card.visualKey || card.path,
        name: card.name,
        depth: card.depth,
        rootName: card.rootName,
        unitCount: card.unitCount,
        startUnit: card.startUnit,
        endUnit: card.endUnit,
        top: card.top || 0,
        height: height,
        originalTop: card.top || 0,
        isCrowded: isCrowded
      };
    });

    for (var pass = 0; pass < 3; pass++) {
      for (var index = 1; index < workingCards.length; index++) {
        nudgeCrowdedPair(workingCards[index - 1], workingCards[index]);
      }
      for (var index = workingCards.length - 2; index >= 0; index--) {
        nudgeCrowdedPair(workingCards[index], workingCards[index + 1]);
      }
    }

    return workingCards.map(function (card) {
      return {
        path: card.path,
        visualKey: card.visualKey || card.path,
        name: card.name,
        depth: card.depth,
        rootName: card.rootName,
        unitCount: card.unitCount,
        startUnit: card.startUnit,
        endUnit: card.endUnit,
        top: Math.round(card.top),
        height: Math.round(card.height),
        zIndex: getDenseCardZIndex(card, card.isCrowded)
      };
    });
  }

  function getAdjustedHierarchyCards(cards) {
    var cardsByLevel = new Map();
    cards.forEach(function (card) {
      var levelCards = cardsByLevel.get(card.depth) || [];
      levelCards.push(card);
      cardsByLevel.set(card.depth, levelCards);
    });

    var out = [];
    cardsByLevel.forEach(function (levelCards) {
      var adjusted = adjustCrowdedLevelCards(levelCards);
      adjusted.forEach(function (c) { out.push(c); });
    });

    return out.sort(function (left, right) {
      return (
        left.depth - right.depth ||
        left.top - right.top ||
        left.startUnit - right.startUnit ||
        left.path.localeCompare(right.path)
      );
    });
  }

  function contiguousUnitRuns(units) {
    var sorted = Array.from(units || []).sort(function (a, b) { return a - b; });
    if (!sorted.length) return [];
    var runs = [[sorted[0]]];
    for (var i = 1; i < sorted.length; i++) {
      var lastRun = runs[runs.length - 1];
      if (sorted[i] === lastRun[lastRun.length - 1] + 1) lastRun.push(sorted[i]);
      else runs.push([sorted[i]]);
    }
    return runs;
  }

  function makeCardFromUnitRun(n, run, top, bottom) {
    var startUnit = run.length ? run[0] : 0;
    var endUnit = run.length ? run[run.length - 1] : startUnit;
    return {
      path: n.path, name: n.name, depth: n.depth,
      visualKey: n.path + '::' + startUnit + '-' + endUnit,
      rootName: splitPath(n.path)[0] || n.name,
      unitCount: run.length,
      startUnit: startUnit,
      endUnit: endUnit,
      top: top, height: Math.max(CARD_MIN_H, bottom - top),
    };
  }

  function getTitleLineBudget(h) {
    return h < 88 ? 1 : 2;
  }
  
  function getCardLabelHeight(height, fontSize) {
    var titleLines = getTitleLineBudget(height);
    var titleHeight = fontSize * 1.2 * titleLines;
    return Math.ceil(titleHeight + 3 + 12);
  }

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
    var cards = [];
    nodes.forEach(function (n) {
      var runs = contiguousUnitRuns(n.units);
      if (!runs.length) {
        cards.push(makeCardFromUnitRun(n, [], STAGE_PAD_TOP, STAGE_PAD_TOP + CARD_MIN_H));
        return;
      }
      runs.forEach(function (units) {
        var tops = [], bots = [];
        units.forEach(function (u) { var mm = metrics.get(u); if (mm) { tops.push(mm.top); bots.push(mm.bottom); } });
        var top = tops.length ? Math.min.apply(null, tops) : STAGE_PAD_TOP;
        var bottom = bots.length ? Math.max.apply(null, bots) : top + CARD_MIN_H;
        cards.push(makeCardFromUnitRun(n, units, top, bottom));
      });
    });
    return getAdjustedHierarchyCards(cards);
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
      var units = Array.from(n.units).sort(function (a, b) { return a - b; });
      var top = tops.length ? Math.min.apply(null, tops) : STAGE_PAD_TOP;
      var bottom = bots.length ? Math.max.apply(null, bots) : top + CARD_MIN_H;
      return {
        path: n.path, name: n.name, depth: n.depth, rootName: splitPath(n.path)[0] || n.name,
        unitCount: n.units.size,
        startUnit: units[0] || 0,
        endUnit: units.length ? units[units.length - 1] : 0,
        top: top, height: Math.max(CARD_MIN_H, bottom - top),
      };
    });
    return getAdjustedHierarchyCards(cards);
  }

  // ── Renderers ────────────────────────────────────────────────────────────
  function railWidth() {
    var currentCardW = CARD_W * Math.max(1, 1 / scale);
    return RAIL_PADDING * 2 + (selectedLevel + 1) * currentCardW + selectedLevel * COL_GAP;
  }

  function renderRail(cards) {
    var rail = document.getElementById('canvas-rail');
    rail.innerHTML = '';
    cards.forEach(function (c) {
      var el = document.createElement('div');
      el.className = 'cv-card' + (c.depth === 0 ? ' cv-card--root' : '')
        + (activePath === c.path ? ' is-active' : '') + (selectedPath === c.path ? ' is-selected' : '');
      el.style.top = c.top + 'px';
      el.style.height = c.height + 'px';
      el.style.setProperty('--topic-card-top', c.top + 'px');
      el.style.setProperty('--topic-card-height', c.height + 'px');
      el.style.setProperty('--cv-accent', accentColor(c.rootName, c.depth));
      el.setAttribute('data-path', c.path);
      el.setAttribute('data-visual-key', c.visualKey || c.path);
      el.setAttribute('data-depth', c.depth);
      el.setAttribute('data-height', c.height);
      el.style.zIndex = c.zIndex || (c.depth === 0 ? 10 : 5);
      
      var content = document.createElement('div');
      content.className = 'cv-card-content';
      
      var name = document.createElement('span');
      name.className = 'cv-card-name';
      name.textContent = c.name;
      
      var meta = document.createElement('span');
      meta.className = 'cv-card-meta';
      meta.textContent = c.unitCount + ' lines';
      
      content.appendChild(name);
      content.appendChild(meta);
      el.appendChild(content);
      
      bindCard(el, c.path);
      rail.appendChild(el);
    });
  }

  function renderCode() {
    var col = document.getElementById('canvas-code-col');
    col.style.display = '';
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
    col.style.display = '';
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

  // ── Side card (right): summary (code mode) or source code (summary mode) ──
  function renderSideCard(cardTopMap) {
    var col = document.getElementById('canvas-side-col');
    col.innerHTML = '';
    if (!activePath) return;
    var node = tree.byPath.get(activePath);
    if (!node) return;
    var accent = accentColor(splitPath(activePath)[0] || activePath, node.depth);
    var topPx = (cardTopMap && cardTopMap[activePath] != null) ? cardTopMap[activePath] : STAGE_PAD_TOP;

    // Compute zoom-scaled width and fonts so floating summary / original code
    // cards remain readable at any canvas scale (mirrors rail title scaling).
    var currentSideW = Math.round(SIDE_W * Math.max(1, 1 / scale));
    var zoomBase = 12 * Math.max(1, 1.25 / scale - 0.25);
    var sideK = Math.max(8, Math.round(10 * (zoomBase / 12)));
    var sideP = Math.max(9, Math.round(12 * (zoomBase / 12)));
    var sideT = Math.max(9, Math.round(13 * (zoomBase / 12)));
    var sideC = Math.max(8, Math.round(11 * (zoomBase / 12)));

    var card = document.createElement('div');
    card.className = 'cv-side-card';
    card.style.top = topPx + 'px';
    card.style.setProperty('--cv-side-w', currentSideW + 'px');
    card.style.setProperty('--cv-accent', accent);
    card.style.setProperty('--cv-side-kicker-size', sideK + 'px');
    card.style.setProperty('--cv-side-path-size', sideP + 'px');
    card.style.setProperty('--cv-side-text-size', sideT + 'px');
    card.style.setProperty('--cv-side-code-size', sideC + 'px');
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
  function setActiveNoScroll(path) {
    activePath = path;
    refreshActiveClasses();
    applyHighlight();
    renderSideCard(lastCardTops);
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
    var wrapHeight = scroll.clientHeight;
    var localTargetY = top;
    var nextY = wrapHeight * 0.2 - localTargetY * scale;
    animateTransform(scale, translateX, nextY);
  }
  function bindCard(el, path) {
    el.addEventListener('mouseenter', function () { if (!selectedPath) setActiveNoScroll(path); });
    el.addEventListener('mouseleave', function () { if (!selectedPath) setActiveNoScroll(null); });
    el.addEventListener('click', function () {
      if (selectedPath === path) { selectedPath = null; setActive(null); }
      else { selectedPath = path; setActive(path); }
    });
  }
  function bindSummaryCard(el, path) {
    el.addEventListener('mouseenter', function () { if (!selectedPath) setActiveNoScroll(path); });
    el.addEventListener('mouseleave', function () { if (!selectedPath) setActiveNoScroll(null); });
    el.addEventListener('click', function () {
      if (selectedPath === path) { selectedPath = null; setActive(null); }
      else { selectedPath = path; setActive(path); }
    });
  }

  // ── Zoom/Pan Transform application ──────────────────────────────────────────
  function setTransform(nextScale, nextX, nextY) {
    scale = nextScale;
    translateX = nextX;
    translateY = nextY;

    var scroll = document.getElementById('canvas-scroll');
    var stage = document.getElementById('canvas-stage');
    if (!scroll || !stage) return;
    
    scroll.style.setProperty('--canvas-translate-x', translateX + 'px');
    scroll.style.setProperty('--canvas-translate-y', translateY + 'px');
    scroll.style.setProperty('--canvas-scale', scale);

    stage.style.transform = 'translate(' + translateX + 'px, ' + translateY + 'px) scale(' + scale + ')';
    
    updateZoomDependentStyles();
  }

  function animateTransform(nextScale, nextX, nextY) {
    var stage = document.getElementById('canvas-stage');
    if (!stage) return;
    stage.classList.add('is-focusing-highlight');
    setTransform(nextScale, nextX, nextY);
    setTimeout(function () {
      stage.classList.remove('is-focusing-highlight');
    }, 380);
  }

  function updateAreaHeight() {
    var scroll = document.getElementById('canvas-scroll');
    if (scroll) {
      scroll.style.setProperty('--canvas-area-height', scroll.clientHeight + 'px');
    }
  }

  function updateZoomDependentStyles() {
    var currentCardW = CARD_W * Math.max(1, 1 / scale);
    
    var rail = document.getElementById('canvas-rail');
    if (rail) {
      var cardEls = rail.querySelectorAll('.cv-card');
      cardEls.forEach(function (el) {
        var depth = parseInt(el.getAttribute('data-depth') || '0', 10);
        var height = parseFloat(el.getAttribute('data-height') || '0');
        
        el.style.left = (RAIL_PADDING + depth * (currentCardW + COL_GAP)) + 'px';
        el.style.setProperty('--cv-card-w', currentCardW + 'px');
        
        var zoomAdjustedFontSize = 12 * Math.max(1, 1.25 / scale - 0.25);
        var titleLines = getTitleLineBudget(height);
        var availableTitleHeight = Math.max(1, height - 16 - 12 - 3);
        var heightCapped = availableTitleHeight / (1.2 * titleLines);
        var fontSize = Math.max(1, Math.min(zoomAdjustedFontSize, heightCapped));
        
        el.style.setProperty('--topic-card-title-font-size', fontSize + 'px');
        el.style.setProperty('--topic-card-title-line-clamp', titleLines);
        el.style.setProperty('--topic-card-label-height', getCardLabelHeight(height, fontSize) + 'px');
      });
    }

    var rw = RAIL_PADDING * 2 + (selectedLevel + 1) * currentCardW + selectedLevel * COL_GAP;
    
    var codeCol = document.getElementById('canvas-code-col');
    if (codeCol) {
      codeCol.style.left = (rw + COL_PAD) + 'px';
      codeCol.style.width = CODE_W + 'px';
    }
    
    var sumCol = document.getElementById('canvas-summary-col');
    if (sumCol) {
      sumCol.style.left = (rw + COL_PAD) + 'px';
      sumCol.style.width = CODE_W + 'px';
    }
    
    var sideCol = document.getElementById('canvas-side-col');
    if (sideCol) {
      sideCol.style.left = (rw + COL_PAD + CODE_W + COL_PAD) + 'px';
      // Keep floating side card (summary / original code) scaled on live zoom
      var sideCard = sideCol.querySelector('.cv-side-card');
      if (sideCard) {
        var currentSideW = Math.round(SIDE_W * Math.max(1, 1 / scale));
        var zoomBase = 12 * Math.max(1, 1.25 / scale - 0.25);
        var sideK = Math.max(8, Math.round(10 * (zoomBase / 12)));
        var sideP = Math.max(9, Math.round(12 * (zoomBase / 12)));
        var sideT = Math.max(9, Math.round(13 * (zoomBase / 12)));
        var sideC = Math.max(8, Math.round(11 * (zoomBase / 12)));
        sideCard.style.setProperty('--cv-side-w', currentSideW + 'px');
        sideCard.style.setProperty('--cv-side-kicker-size', sideK + 'px');
        sideCard.style.setProperty('--cv-side-path-size', sideP + 'px');
        sideCard.style.setProperty('--cv-side-text-size', sideT + 'px');
        sideCard.style.setProperty('--cv-side-code-size', sideC + 'px');
      }
    }
    
    var stage = document.getElementById('canvas-stage');
    if (stage) {
      var currentSideWForMin = Math.round(SIDE_W * Math.max(1, 1 / scale));
      stage.style.minWidth = (rw + COL_PAD + CODE_W + COL_PAD + currentSideWForMin + COL_PAD) + 'px';
      
      var contentCol = document.getElementById(summaryMode ? 'canvas-summary-col' : 'canvas-code-col');
      var railH = 0;
      if (rail) {
        var cardEls = rail.querySelectorAll('.cv-card');
        cardEls.forEach(function (el) {
          var top = parseFloat(el.style.top || '0');
          var height = parseFloat(el.style.height || '0');
          if (top + height > railH) railH = top + height;
        });
      }
      var contentH = contentCol ? contentCol.offsetTop + contentCol.offsetHeight : 0;
      stage.style.height = (Math.max(railH, contentH) + STAGE_PAD_TOP + 40) + 'px';
    }
  }

  function bindDragAndZoom() {
    var scrollEl = document.getElementById('canvas-scroll');
    if (!scrollEl) return;
    
    scrollEl.addEventListener('mousedown', function (e) {
      if (e.target.closest('button, select, input, a, .cv-card, .cv-sum-card')) return;
      if (e.button !== 0) return;
      
      isDragging = true;
      userMoved = true;
      scrollEl.classList.add('is-dragging');
      lastMouseX = e.clientX;
      lastMouseY = e.clientY;
      
      e.preventDefault();
      
      function onMouseMove(mv) {
        if (!isDragging) return;
        var dx = mv.clientX - lastMouseX;
        var dy = mv.clientY - lastMouseY;
        lastMouseX = mv.clientX;
        lastMouseY = mv.clientY;
        
        setTransform(scale, translateX + dx, translateY + dy);
      }
      
      function onMouseUp() {
        isDragging = false;
        scrollEl.classList.remove('is-dragging');
        window.removeEventListener('mousemove', onMouseMove);
        window.removeEventListener('mouseup', onMouseUp);
      }
      
      window.addEventListener('mousemove', onMouseMove);
      window.addEventListener('mouseup', onMouseUp);
    });
    
    scrollEl.addEventListener('wheel', function (e) {
      e.preventDefault();
      var currentScale = scale;
      var delta = e.deltaY > 0 ? 1 / 1.12 : 1.12;
      var nextScale = Math.min(3.0, Math.max(0.3, currentScale * delta));
      if (nextScale === currentScale) return;
      
      var wrapRect = scrollEl.getBoundingClientRect();
      var cursorX = e.clientX - wrapRect.left;
      var cursorY = e.clientY - wrapRect.top;
      
      var cx = (cursorX - translateX) / currentScale;
      var cy = (cursorY - translateY) / currentScale;
      
      var nextX = cursorX - cx * nextScale;
      var nextY = cursorY - cy * nextScale;
      
      userMoved = true;
      setTransform(nextScale, nextX, nextY);
    }, { passive: false });
    
    document.getElementById('cv-zoom-in').addEventListener('click', function () {
      animateTransform(Math.min(3.0, scale * 1.2), translateX, translateY);
    });
    document.getElementById('cv-zoom-out').addEventListener('click', function () {
      animateTransform(Math.max(0.3, scale / 1.2), translateX, translateY);
    });
    document.getElementById('cv-zoom-reset').addEventListener('click', function () {
      animateTransform(1.0, 40, 40);
    });
    
    var ARROW_STEP = 80;
    document.getElementById('cv-nav-top').addEventListener('click', function () {
      animateTransform(scale, translateX, 40);
    });
    document.getElementById('cv-nav-prev').addEventListener('click', function () {
      var pageStep = Math.max(120, scrollEl.clientHeight * 0.8);
      animateTransform(scale, translateX, translateY + pageStep);
    });
    document.getElementById('cv-nav-next').addEventListener('click', function () {
      var pageStep = Math.max(120, scrollEl.clientHeight * 0.8);
      animateTransform(scale, translateX, translateY - pageStep);
    });
    document.getElementById('cv-nav-bot').addEventListener('click', function () {
      var stage = document.getElementById('canvas-stage');
      var nextY = Math.min(40, scrollEl.clientHeight - stage.offsetHeight * scale - 40);
      animateTransform(scale, translateX, nextY);
    });
    
    var foldBtn = document.getElementById('cv-fold-btn');
    var controls = document.getElementById('canvas-controls');
    foldBtn.addEventListener('click', function () {
      var isFolded = controls.classList.contains('is-folded');
      controls.classList.toggle('is-folded', !isFolded);
      foldBtn.textContent = isFolded ? '⊟' : '⊞';
      foldBtn.title = isFolded ? 'Collapse controls' : 'Expand controls';
    });
    
    var orientBtn = document.getElementById('cv-orient-btn');
    orientBtn.addEventListener('click', function () {
      var isHorizontal = controls.classList.contains('is-horizontal');
      controls.classList.toggle('is-horizontal', !isHorizontal);
      orientBtn.textContent = isHorizontal ? '⬌' : '⬍';
      orientBtn.title = isHorizontal ? 'Switch to vertical' : 'Switch to horizontal';
    });

    window.addEventListener('keydown', function (e) {
      if (!built) return;
      var canvasView = document.getElementById('canvas-view');
      if (!canvasView || canvasView.style.display === 'none') return;
      
      var t = e.target;
      var tag = t ? t.tagName : '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable)) {
        return;
      }
      
      if (e.key === 'Home') {
        e.preventDefault();
        animateTransform(scale, translateX, 40);
      } else if (e.key === 'End') {
        e.preventDefault();
        var stage = document.getElementById('canvas-stage');
        var nextY = Math.min(40, scrollEl.clientHeight - stage.offsetHeight * scale - 40);
        animateTransform(scale, translateX, nextY);
      } else if (e.key === 'PageUp') {
        e.preventDefault();
        var pageStep = Math.max(120, scrollEl.clientHeight * 0.8);
        animateTransform(scale, translateX, translateY + pageStep);
      } else if (e.key === 'PageDown') {
        e.preventDefault();
        var pageStep = Math.max(120, scrollEl.clientHeight * 0.8);
        animateTransform(scale, translateX, translateY - pageStep);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setTransform(scale, translateX, translateY + ARROW_STEP);
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        setTransform(scale, translateX, translateY - ARROW_STEP);
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        setTransform(scale, translateX + ARROW_STEP, translateY);
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        setTransform(scale, translateX - ARROW_STEP, translateY);
      } else if (e.key === '+' || e.key === '=') {
        e.preventDefault();
        animateTransform(Math.min(3.0, scale * 1.2), translateX, translateY);
      } else if (e.key === '-' || e.key === '_') {
        e.preventDefault();
        animateTransform(Math.max(0.3, scale / 1.2), translateX, translateY);
      }
    });
  }

  // ── Full (re)layout pass ──────────────────────────────────────────────────
  var tree = null, lastCardTops = {};
  function relayout() {
    if (summaryMode) renderSummaries(); else renderCode();

    // Measure after the content column has laid out, then position rail/side.
    requestAnimationFrame(function () {
      var cards = summaryMode ? layoutCardsSummary() : layoutCards(measureCodeMetrics());
      lastCardTops = {};
      cards.forEach(function (c) {
        if (lastCardTops[c.path] == null || c.top < lastCardTops[c.path]) lastCardTops[c.path] = c.top;
      });
      renderRail(cards);
      renderSideCard(lastCardTops);
      applyHighlight();
      updateZoomDependentStyles();
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
      + '<span class="cv-hint">drag to pan · wheel to zoom · hover to align</span>'
      + '</div>'
      + '<div id="canvas-scroll"><div id="canvas-stage">'
      + '<div id="canvas-rail"></div>'
      + '<div id="canvas-code-col"><pre id="canvas-code"></pre></div>'
      + '<div id="canvas-summary-col"></div>'
      + '<div id="canvas-side-col"></div>'
      + '</div>'
      + '<div id="canvas-controls" class="canvas-controls">'
      + '  <div class="canvas-controls-header">'
      + '    <button type="button" class="canvas-zoom-btn" id="cv-fold-btn" title="Collapse controls">⊟</button>'
      + '    <button type="button" class="canvas-zoom-btn" id="cv-orient-btn" title="Switch layout">⬌</button>'
      + '  </div>'
      + '  <div class="canvas-controls-body" id="cv-controls-body">'
      + '    <button type="button" class="canvas-zoom-btn" id="cv-nav-top" title="Scroll to top">⇈</button>'
      + '    <button type="button" class="canvas-zoom-btn" id="cv-nav-prev" title="Previous page">↑</button>'
      + '    <button type="button" class="canvas-zoom-btn" id="cv-nav-next" title="Next page">↓</button>'
      + '    <button type="button" class="canvas-zoom-btn" id="cv-nav-bot" title="Scroll to bottom">⇊</button>'
      + '    <div class="canvas-spacer"></div>'
      + '    <button type="button" class="canvas-zoom-btn" id="cv-zoom-in" title="Zoom in">+</button>'
      + '    <button type="button" class="canvas-zoom-btn" id="cv-zoom-out" title="Zoom out">−</button>'
      + '    <button type="button" class="canvas-zoom-btn" id="cv-zoom-reset" title="Reset zoom">⊙</button>'
      + '  </div>'
      + '</div>'
      + '</div>';
    document.getElementById('canvas-mode-toggle').addEventListener('click', function () {
      summaryMode = !summaryMode;
      selectedPath = null; activePath = null;
      this.classList.toggle('is-summary', summaryMode);
      this.textContent = summaryMode ? 'Show code' : 'Show summaries';
      relayout();
    });
    
    bindDragAndZoom();
    
    window.addEventListener('resize', function () {
      if (built) {
        updateAreaHeight();
        updateZoomDependentStyles();
      }
    });
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
    
    scale = 1.0;
    translateX = 40;
    translateY = 40;
    setTransform(scale, translateX, translateY);
    updateAreaHeight();
    
    relayout();
    built = true;
  }

  // Exposed for the tab switcher to call lazily on first activation. Idempotent.
  window.__buildCanvas = build;
})();
"""
