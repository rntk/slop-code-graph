"""Generate a fully self-contained HTML call-graph visualization.

The visualization is rendered by a small, hand-written SVG graph engine that is
embedded directly in the output (see ``ENGINE_SCRIPT``). It replaces the former
runtime dependency on the Cytoscape.js / dagre / fuse.js CDN bundles, so the
generated HTML has **no external dependencies whatsoever**: it ships its own
graph data model, layered/force-directed/concentric layouts, pan/zoom/drag,
fuzzy search and flowchart renderer. The file opens in any modern browser with
no server and no network access.
"""

from __future__ import annotations

import html
import json

from .graph_builder import CallGraph

# ---------------------------------------------------------------------------
# Embedded SVG graph engine  (replaces cytoscape + dagre + cytoscape-dagre)
# ---------------------------------------------------------------------------
# A minimal, dependency-free engine: a node/edge data model rendered to SVG,
# three layouts (layered "dagre", force-directed "cose", "concentric"),
# pan/zoom/drag, selection and CSS-class styling. Both the main call graph and
# the flowchart view are built on top of it.
#
# Injected verbatim into the template (no str.format), so it must not contain
# the literal sequence "</" (would prematurely close the <script>) or the
# "@@...@@" placeholder tokens used by render().

ENGINE_SCRIPT = r"""
const SVGNS = 'http://www.w3.org/2000/svg';
let GV_SEQ = 0;

function svgEl(tag, attrs) {
  const el = document.createElementNS(SVGNS, tag);
  if (attrs) for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

// Map a space-separated class string to a node shape (used by the flow view,
// where shapes are derived from semantic classes rather than a callback).
function shapeFromClasses(cls) {
  if (/flow-decision|flow-switch/.test(cls)) return 'diamond';
  if (/flow-loop/.test(cls))                 return 'hexagon';
  if (/flow-entry/.test(cls))                return 'pentagon';
  if (/flow-connector/.test(cls))            return 'ellipse';
  return 'round-rectangle';
}

function sizeForShape(shape, tw, th) {
  const PADX = 12, PADY = 8;
  switch (shape) {
    case 'diamond':  return { w: Math.max(60, tw * 1.8 + PADX), h: Math.max(44, th * 2 + PADY) };
    case 'hexagon':  return { w: Math.max(60, tw + PADX * 2 + 24), h: Math.max(30, th + PADY * 2) };
    case 'pentagon': return { w: Math.max(54, tw + PADX * 2), h: Math.max(32, th + PADY * 2 + 6) };
    case 'ellipse':  return { w: 14, h: 14 };
    default:         return { w: Math.max(40, tw + PADX * 2), h: Math.max(26, th + PADY * 2) };
  }
}

function shapeEl(shape, w, h) {
  const hw = w / 2, hh = h / 2;
  const poly = (pts) => svgEl('polygon', { points: pts, class: 'shape' });
  switch (shape) {
    case 'diamond':  return poly(`0,${-hh} ${hw},0 0,${hh} ${-hw},0`);
    case 'hexagon': {
      const c = Math.min(hh, hw * 0.5);
      return poly(`${-hw + c},${-hh} ${hw - c},${-hh} ${hw},0 ${hw - c},${hh} ${-hw + c},${hh} ${-hw},0`);
    }
    case 'pentagon': return poly(`${-hw},${-hh} ${hw},${-hh} ${hw},${hh * 0.3} 0,${hh} ${-hw},${hh * 0.3}`);
    case 'ellipse':  return svgEl('circle', { r: hw, cx: 0, cy: 0, class: 'shape' });
    case 'round-tag': return svgEl('rect', { x: -hw, y: -hh, width: w, height: h, rx: hh, ry: hh, class: 'shape' });
    default:         return svgEl('rect', { x: -hw, y: -hh, width: w, height: h, rx: 6, ry: 6, class: 'shape' });
  }
}

// Point on node n's bounding box on the ray toward (tx, ty).
function borderPt(n, tx, ty) {
  const dx = tx - n.x, dy = ty - n.y;
  if (dx === 0 && dy === 0) return { x: n.x, y: n.y };
  const hw = n.w / 2, hh = n.h / 2;
  const s = 1 / Math.max(Math.abs(dx) / hw, Math.abs(dy) / hh);
  return { x: n.x + dx * s, y: n.y + dy * s };
}

class GraphView {
  constructor(container, opts) {
    this.c = container;
    this.o = opts || {};
    this.N = new Map();      // id -> node obj
    this.E = new Map();      // id -> edge obj
    this.outE = new Map();   // id -> [edgeId]
    this.inE = new Map();    // id -> [edgeId]
    this.t = { x: 0, y: 0, k: 1 };
    this.minZoom = 0.02;
    this.maxZoom = 8;
    this._id = ++GV_SEQ;
    this._build();
  }

  _build() {
    const svg = svgEl('svg', { class: 'gv-svg' });
    this.svg = svg;
    const defs = svgEl('defs');
    const mk = svgEl('marker', {
      id: 'arr' + this._id, viewBox: '0 0 10 10', refX: 9, refY: 5,
      markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse',
    });
    // context-stroke makes the arrowhead follow each edge's stroke colour, so
    // one marker serves every edge state (default / highlighted / flow-*).
    mk.appendChild(svgEl('path', { d: 'M0,0 L10,5 L0,10 z', fill: 'context-stroke' }));
    defs.appendChild(mk);
    svg.appendChild(defs);

    this.vp = svgEl('g');
    svg.appendChild(this.vp);
    this.eLayer = svgEl('g', { class: 'edges' });
    this.nLayer = svgEl('g', { class: 'nodes' });
    this.vp.appendChild(this.eLayer);
    this.vp.appendChild(this.nLayer);

    this.c.innerHTML = '';
    this.c.appendChild(svg);

    (this.o.nodes || []).forEach((it) => this._addNode(it));
    (this.o.edges || []).forEach((it) => this._addEdge(it));
    this._wire();
    this._applyT();
  }

  _addNode(it) {
    const data = it.data || it;
    const cls = this.o.nodeClasses ? this.o.nodeClasses(data) : (it.classes || '');
    const label = this.o.labelOf
      ? this.o.labelOf(data)
      : (data.label != null ? data.label : (data.name || ''));
    const shape = this.o.shapeOf ? this.o.shapeOf(data) : shapeFromClasses(cls);
    const fill = this.o.fillOf ? this.o.fillOf(data) : null;

    const g = svgEl('g', { class: 'node ' + cls });
    g.__gid = data.id;
    this.nLayer.appendChild(g);

    const hasText = String(label) !== '' && shape !== 'ellipse';
    let tw = 0, th = 0;
    if (hasText) {
      const txt = svgEl('text', { class: 'nlabel', 'text-anchor': 'middle', 'dominant-baseline': 'central' });
      const lines = String(label).split('\n');
      const lh = 12;
      lines.forEach((ln, i) => {
        const ts = svgEl('tspan', { x: 0 });
        ts.setAttribute('dy', i === 0 ? -(lines.length - 1) * lh / 2 : lh);
        ts.textContent = ln;
        txt.appendChild(ts);
      });
      g.appendChild(txt);
      const bb = txt.getBBox();
      tw = bb.width; th = bb.height;
    }

    const sz = sizeForShape(shape, tw, th);
    const shp = shapeEl(shape, sz.w, sz.h);
    if (fill) shp.style.fill = fill;
    g.insertBefore(shp, g.firstChild);

    this.N.set(data.id, { data, g, shp, w: sz.w, h: sz.h, x: 0, y: 0, hidden: false, cls });
    this.outE.set(data.id, []);
    this.inE.set(data.id, []);
  }

  _addEdge(it) {
    const data = it.data || it;
    const cls = this.o.edgeClasses ? this.o.edgeClasses(data) : (it.classes || '');
    const label = this.o.edgeLabelOf ? this.o.edgeLabelOf(data) : (data.label || '');

    const path = svgEl('path', { class: 'edge ' + cls });
    path.setAttribute('marker-end', 'url(#arr' + this._id + ')');
    this.eLayer.appendChild(path);

    let lblEl = null, lblBg = null;
    if (label) {
      lblBg = svgEl('rect', { class: 'edge-label-bg' });
      lblEl = svgEl('text', { class: 'edge-label ' + cls, 'text-anchor': 'middle', 'dominant-baseline': 'central' });
      lblEl.textContent = label;
      this.eLayer.appendChild(lblBg);
      this.eLayer.appendChild(lblEl);
    }

    this.E.set(data.id, { data, path, lblEl, lblBg, cls, hidden: false });
    if (this.outE.has(data.source)) this.outE.get(data.source).push(data.id);
    if (this.inE.has(data.target)) this.inE.get(data.target).push(data.id);
  }

  // ---- transform / interaction ------------------------------------------
  _applyT() {
    this.vp.setAttribute('transform', `translate(${this.t.x},${this.t.y}) scale(${this.t.k})`);
  }

  _wire() {
    const svg = this.svg;
    let mode = null, last = null, dragNode = null, moved = 0, downId = null;
    const toLocal = (e) => {
      const r = svg.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };
    svg.addEventListener('pointerdown', (e) => {
      const ng = e.target.closest ? e.target.closest('.node') : null;
      last = toLocal(e); moved = 0;
      if (ng) { downId = ng.__gid; dragNode = this.N.get(downId); mode = 'node'; }
      else { mode = 'pan'; downId = null; }
      try { svg.setPointerCapture(e.pointerId); } catch (err) {}
    });
    svg.addEventListener('pointermove', (e) => {
      if (!mode) return;
      const p = toLocal(e);
      const dx = p.x - last.x, dy = p.y - last.y;
      moved += Math.abs(dx) + Math.abs(dy);
      last = p;
      if (mode === 'pan') { this.t.x += dx; this.t.y += dy; this._applyT(); }
      else if (mode === 'node' && dragNode) {
        dragNode.x += dx / this.t.k; dragNode.y += dy / this.t.k;
        dragNode.g.setAttribute('transform', `translate(${dragNode.x},${dragNode.y})`);
        this._redrawIncident(downId);
      }
    });
    const up = () => {
      if (!mode) return;
      if (moved < 4) {
        if (downId) {
          this.selectOnly(downId);
          if (this.o.onNodeTap) this.o.onNodeTap(this.N.get(downId).data);
        } else {
          this.unselectAll();
          if (this.o.onBgTap) this.o.onBgTap();
        }
      }
      mode = null; dragNode = null; downId = null;
    };
    svg.addEventListener('pointerup', up);
    svg.addEventListener('pointercancel', up);
    svg.addEventListener('wheel', (e) => {
      e.preventDefault();
      const p = toLocal(e);
      const f = e.deltaY < 0 ? 1.12 : 1 / 1.12;
      const nk = Math.max(this.minZoom, Math.min(this.maxZoom, this.t.k * f));
      this.t.x = p.x - (p.x - this.t.x) / this.t.k * nk;
      this.t.y = p.y - (p.y - this.t.y) / this.t.k * nk;
      this.t.k = nk;
      this._applyT();
    }, { passive: false });
  }

  // ---- drawing ----------------------------------------------------------
  _positionNodes() {
    this.N.forEach((n) => {
      n.g.style.display = n.hidden ? 'none' : '';
      if (!n.hidden) n.g.setAttribute('transform', `translate(${n.x},${n.y})`);
    });
  }

  _redrawEdge(eo) {
    const s = this.N.get(eo.data.source), t = this.N.get(eo.data.target);
    const hide = !s || !t || s.hidden || t.hidden || eo.hidden;
    if (hide) {
      eo.path.style.display = 'none';
      if (eo.lblEl) { eo.lblEl.style.display = 'none'; eo.lblBg.style.display = 'none'; }
      return;
    }
    eo.path.style.display = '';
    let d, mid;
    if (s === t) {
      const hw = s.w / 2, hh = s.h / 2, x = s.x, y = s.y;
      d = `M ${x + hw * 0.4} ${y - hh} C ${x + hw + 50} ${y - hh - 40} ${x + hw + 50} ${y + hh + 40} ${x + hw * 0.4} ${y + hh}`;
      mid = { x: x + hw + 40, y: y };
    } else {
      const p0 = borderPt(s, t.x, t.y), p1 = borderPt(t, s.x, s.y);
      if (eo.cls.indexOf('loopback') >= 0) {
        const mx = (p0.x + p1.x) / 2, my = (p0.y + p1.y) / 2;
        const dx = p1.x - p0.x, dy = p1.y - p0.y;
        const len = Math.hypot(dx, dy) || 1;
        const nx = -dy / len, ny = dx / len;
        const off = Math.min(80, len * 0.4) + 30;
        const cx = mx + nx * off, cy = my + ny * off;
        d = `M ${p0.x} ${p0.y} Q ${cx} ${cy} ${p1.x} ${p1.y}`;
        mid = { x: 0.25 * p0.x + 0.5 * cx + 0.25 * p1.x, y: 0.25 * p0.y + 0.5 * cy + 0.25 * p1.y };
      } else {
        d = `M ${p0.x} ${p0.y} L ${p1.x} ${p1.y}`;
        mid = { x: (p0.x + p1.x) / 2, y: (p0.y + p1.y) / 2 };
      }
    }
    eo.path.setAttribute('d', d);
    if (eo.lblEl) {
      eo.lblEl.style.display = ''; eo.lblBg.style.display = '';
      eo.lblEl.setAttribute('x', mid.x); eo.lblEl.setAttribute('y', mid.y);
      const bb = eo.lblEl.getBBox();
      eo.lblBg.setAttribute('x', bb.x - 2); eo.lblBg.setAttribute('y', bb.y - 1);
      eo.lblBg.setAttribute('width', bb.width + 4); eo.lblBg.setAttribute('height', bb.height + 2);
    }
  }

  _redrawIncident(id) {
    const ids = (this.outE.get(id) || []).concat(this.inE.get(id) || []);
    ids.forEach((eid) => this._redrawEdge(this.E.get(eid)));
  }

  _redraw() {
    this._positionNodes();
    this.E.forEach((e) => this._redrawEdge(e));
  }

  // ---- layouts ----------------------------------------------------------
  layout(name, opts) {
    opts = opts || {};
    if (name === 'dagre') this._dagre(opts.rankDir || 'TB', opts.nodeSep || 34, opts.rankSep || 90);
    else if (name === 'cose') this._cose();
    else if (name === 'concentric') this._concentric();
    this._redraw();
    this.fit(40);
  }

  _dagre(rankDir, nodeSep, rankSep) {
    const all = [...this.N.keys()].filter((i) => !this.N.get(i).hidden);
    if (!all.length) return;
    const idset = new Set(all);
    const E = [];
    this.E.forEach((e) => {
      if (e.hidden) return;
      const s = e.data.source, t = e.data.target;
      if (s !== t && idset.has(s) && idset.has(t)) E.push([s, t]);
    });

    // 1. Break cycles: iterative DFS, mark edges pointing back to an ancestor.
    const adj = new Map(all.map((i) => [i, []]));
    E.forEach(([s, t]) => adj.get(s).push(t));
    const SEP = ' ';
    const state = new Map();   // 1 = on stack, 2 = done
    const reversed = new Set();
    for (const root of all) {
      if (state.get(root)) continue;
      const stack = [[root, 0]];
      state.set(root, 1);
      while (stack.length) {
        const fr = stack[stack.length - 1];
        const nbrs = adj.get(fr[0]);
        if (fr[1] < nbrs.length) {
          const v = nbrs[fr[1]++];
          const st = state.get(v) || 0;
          if (st === 1) reversed.add(fr[0] + SEP + v);
          else if (st === 0) { state.set(v, 1); stack.push([v, 0]); }
        } else { state.set(fr[0], 2); stack.pop(); }
      }
    }
    const AE = E.map(([s, t]) => (reversed.has(s + SEP + t) ? [t, s] : [s, t]));

    // 2. Longest-path ranking on the now-acyclic edge set.
    const indeg = new Map(all.map((i) => [i, 0]));
    const out = new Map(all.map((i) => [i, []]));
    AE.forEach(([s, t]) => { out.get(s).push(t); indeg.set(t, indeg.get(t) + 1); });
    const rank = new Map(all.map((i) => [i, 0]));
    const q = all.filter((i) => indeg.get(i) === 0);
    let qi = 0;
    while (qi < q.length) {
      const u = q[qi++];
      for (const v of out.get(u)) {
        if (rank.get(v) < rank.get(u) + 1) rank.set(v, rank.get(u) + 1);
        indeg.set(v, indeg.get(v) - 1);
        if (indeg.get(v) === 0) q.push(v);
      }
    }

    const maxRank = Math.max(0, ...all.map((i) => rank.get(i)));
    const layers = Array.from({ length: maxRank + 1 }, () => []);
    all.forEach((i) => layers[rank.get(i)].push(i));

    // 3. Reduce crossings: barycenter sweeps.
    const nbrUp = new Map(all.map((i) => [i, []]));
    const nbrDown = new Map(all.map((i) => [i, []]));
    AE.forEach(([s, t]) => { nbrDown.get(s).push(t); nbrUp.get(t).push(s); });
    const pos = new Map();
    layers.forEach((L) => L.forEach((id, i) => pos.set(id, i)));
    const bc = (id, m) => {
      const ns = m.get(id);
      if (!ns.length) return pos.get(id);
      let s = 0; ns.forEach((x) => (s += pos.get(x)));
      return s / ns.length;
    };
    for (let it = 0; it < 6; it++) {
      if (it % 2 === 0) {
        for (let r = 1; r < layers.length; r++) {
          layers[r].sort((a, b) => bc(a, nbrUp) - bc(b, nbrUp));
          layers[r].forEach((id, i) => pos.set(id, i));
        }
      } else {
        for (let r = layers.length - 2; r >= 0; r--) {
          layers[r].sort((a, b) => bc(a, nbrDown) - bc(b, nbrDown));
          layers[r].forEach((id, i) => pos.set(id, i));
        }
      }
    }

    // 4. Coordinate assignment. rankDir maps rank->main axis, order->cross axis.
    const horizontal = rankDir === 'LR';
    const mainC = []; let acc = 0;
    for (let r = 0; r < layers.length; r++) {
      let mx = 0;
      layers[r].forEach((id) => { const n = this.N.get(id); mx = Math.max(mx, horizontal ? n.w : n.h); });
      mainC[r] = acc + mx / 2;
      acc += mx + rankSep;
    }
    const cross = new Map();
    layers.forEach((L) => {
      let c = 0;
      L.forEach((id, i) => {
        const n = this.N.get(id);
        const cs = horizontal ? n.h : n.w;
        if (i > 0) c += nodeSep;
        c += cs / 2; cross.set(id, c); c += cs / 2;
      });
      const shift = -c / 2;
      L.forEach((id) => cross.set(id, cross.get(id) + shift));
    });

    // Light centering refinement: pull each node toward neighbour barycenter,
    // then push apart to remove overlaps. Improves straightness of long paths.
    const sizeCross = (id) => { const n = this.N.get(id); return horizontal ? n.h : n.w; };
    for (let it = 0; it < 4; it++) {
      const m = it % 2 === 0 ? nbrUp : nbrDown;
      const order = it % 2 === 0 ? layers : [...layers].reverse();
      for (const L of order) {
        if (!L.length) continue;
        for (let i = 0; i < L.length; i++) {
          const ns = m.get(L[i]);
          if (ns.length) { let s = 0; ns.forEach((x) => (s += cross.get(x))); cross.set(L[i], s / ns.length); }
        }
        const sortedL = [...L].sort((a, b) => cross.get(a) - cross.get(b));
        for (let i = 1; i < sortedL.length; i++) {
          const p = sortedL[i - 1], c2 = sortedL[i];
          const gap = (sizeCross(p) + sizeCross(c2)) / 2 + nodeSep;
          if (cross.get(c2) - cross.get(p) < gap) cross.set(c2, cross.get(p) + gap);
        }
      }
    }

    all.forEach((id) => {
      const n = this.N.get(id);
      if (horizontal) { n.x = mainC[rank.get(id)]; n.y = cross.get(id); }
      else { n.x = cross.get(id); n.y = mainC[rank.get(id)]; }
    });
  }

  _cose() {
    const ids = [...this.N.keys()].filter((i) => !this.N.get(i).hidden);
    const n = ids.length;
    if (!n) return;
    const R = Math.max(200, n * 28);
    const pos = new Map();
    ids.forEach((id, i) => { const a = 2 * Math.PI * i / n; pos.set(id, { x: Math.cos(a) * R, y: Math.sin(a) * R }); });
    const edges = [];
    this.E.forEach((e) => {
      if (e.hidden) return;
      const s = e.data.source, t = e.data.target;
      if (s !== t && pos.has(s) && pos.has(t)) edges.push([s, t]);
    });
    const k = 120, area = k * k;
    let temp = R;
    const iters = n > 400 ? 150 : 280;
    for (let it = 0; it < iters; it++) {
      const disp = new Map(ids.map((i) => [i, { x: 0, y: 0 }]));
      for (let a = 0; a < n; a++) {
        for (let b = a + 1; b < n; b++) {
          const pa = pos.get(ids[a]), pb = pos.get(ids[b]);
          const dx = pa.x - pb.x, dy = pa.y - pb.y;
          const dist = Math.hypot(dx, dy) || 0.01;
          const rep = area / dist;
          const ux = dx / dist, uy = dy / dist;
          const da = disp.get(ids[a]), db = disp.get(ids[b]);
          da.x += ux * rep; da.y += uy * rep; db.x -= ux * rep; db.y -= uy * rep;
        }
      }
      edges.forEach(([s, t]) => {
        const ps = pos.get(s), pt = pos.get(t);
        const dx = ps.x - pt.x, dy = ps.y - pt.y;
        const dist = Math.hypot(dx, dy) || 0.01;
        const att = dist * dist / k;
        const ux = dx / dist, uy = dy / dist;
        const ds = disp.get(s), dt = disp.get(t);
        ds.x -= ux * att; ds.y -= uy * att; dt.x += ux * att; dt.y += uy * att;
      });
      ids.forEach((id) => {
        const d = disp.get(id);
        const dl = Math.hypot(d.x, d.y) || 0.01;
        const p = pos.get(id);
        p.x += d.x / dl * Math.min(dl, temp);
        p.y += d.y / dl * Math.min(dl, temp);
      });
      temp *= 0.97;
    }
    ids.forEach((id) => { const p = pos.get(id), nn = this.N.get(id); nn.x = p.x; nn.y = p.y; });
  }

  _concentric() {
    const ids = [...this.N.keys()].filter((i) => !this.N.get(i).hidden);
    if (!ids.length) return;
    const deg = new Map(ids.map((i) => [i, 0]));
    this.E.forEach((e) => {
      if (e.hidden) return;
      if (deg.has(e.data.source)) deg.set(e.data.source, deg.get(e.data.source) + 1);
      if (deg.has(e.data.target)) deg.set(e.data.target, deg.get(e.data.target) + 1);
    });
    const sorted = [...ids].sort((a, b) => deg.get(b) - deg.get(a));
    const maxd = deg.get(sorted[0]) || 0;
    const levels = {};
    sorted.forEach((id) => {
      const l = Math.floor((maxd - deg.get(id)) / 2);  // levelWidth ~ 2
      (levels[l] = levels[l] || []).push(id);
    });
    const lvKeys = Object.keys(levels).map(Number).sort((a, b) => a - b);
    lvKeys.forEach((l, li) => {
      const arr = levels[l];
      const cnt = arr.length;
      const r = li === 0 && cnt === 1 ? 0 : (li === 0 ? 120 : li * 170);
      arr.forEach((id, i) => {
        const a = 2 * Math.PI * i / Math.max(1, cnt) - Math.PI / 2;
        const nn = this.N.get(id);
        nn.x = r === 0 ? 0 : Math.cos(a) * r;
        nn.y = r === 0 ? 0 : Math.sin(a) * r;
      });
    });
  }

  // ---- viewport helpers -------------------------------------------------
  _fitBox(nodes, pad) {
    if (!nodes.length) return;
    pad = pad == null ? 40 : pad;
    let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
    nodes.forEach((n) => {
      minX = Math.min(minX, n.x - n.w / 2); maxX = Math.max(maxX, n.x + n.w / 2);
      minY = Math.min(minY, n.y - n.h / 2); maxY = Math.max(maxY, n.y + n.h / 2);
    });
    const cw = this.c.clientWidth || 800, ch = this.c.clientHeight || 600;
    const w = Math.max(1, maxX - minX), h = Math.max(1, maxY - minY);
    let k = Math.min((cw - 2 * pad) / w, (ch - 2 * pad) / h);
    k = Math.max(this.minZoom, Math.min(this.maxZoom, k));
    this.t.k = k;
    this.t.x = cw / 2 - (minX + maxX) / 2 * k;
    this.t.y = ch / 2 - (minY + maxY) / 2 * k;
    this._applyT();
  }

  fit(pad) {
    this._fitBox([...this.N.values()].filter((n) => !n.hidden), pad);
  }

  center(ids, pad) {
    this._fitBox(ids.map((i) => this.N.get(i)).filter((n) => n && !n.hidden), pad);
  }

  zoomBy(f) {
    const cx = (this.c.clientWidth || 800) / 2, cy = (this.c.clientHeight || 600) / 2;
    const nk = Math.max(this.minZoom, Math.min(this.maxZoom, this.t.k * f));
    this.t.x = cx - (cx - this.t.x) / this.t.k * nk;
    this.t.y = cy - (cy - this.t.y) / this.t.k * nk;
    this.t.k = nk;
    this._applyT();
  }

  // ---- selection / classes / visibility ---------------------------------
  selectOnly(id) { this.unselectAll(); const n = this.N.get(id); if (n) n.g.classList.add('selected'); }
  unselectAll() { this.N.forEach((n) => n.g.classList.remove('selected')); }
  nodeClass(id, cls, on) { const n = this.N.get(id); if (n) n.g.classList.toggle(cls, !!on); }
  edgeClass(id, cls, on) {
    const e = this.E.get(id);
    if (!e) return;
    e.path.classList.toggle(cls, !!on);
    if (e.lblEl) e.lblEl.classList.toggle(cls, !!on);
  }
  forEachNode(cb) { this.N.forEach((n, id) => cb(id, n.data)); }
  forEachEdge(cb) { this.E.forEach((e, id) => cb(id, e.data)); }
  showNode(id, on) { const n = this.N.get(id); if (n) n.hidden = !on; }
  showEdge(id, on) { const e = this.E.get(id); if (e) { e.hidden = !on; this._redrawEdge(e); } }
  data(id) { const n = this.N.get(id); return n ? n.data : null; }
  destroy() { this.c.innerHTML = ''; }
}

// Tiny fuzzy matcher (replaces fuse.js). Returns a score, or -1 for no match.
function fuzzyScore(needle, hay) {
  if (!needle) return 0;
  needle = needle.toLowerCase();
  hay = String(hay || '').toLowerCase();
  const idx = hay.indexOf(needle);
  if (idx >= 0) return 100 - idx - (hay.length - needle.length) * 0.1;
  let hi = 0, ni = 0, gaps = 0, last = -1;
  for (; ni < needle.length && hi < hay.length; hi++) {
    if (needle[ni] === hay[hi]) { if (last >= 0) gaps += hi - last - 1; last = hi; ni++; }
  }
  if (ni < needle.length) return -1;
  return 40 - gaps * 0.5;
}

function fuzzySearch(query, items, keys, limit) {
  const q = query.trim();
  if (!q) return [];
  const scored = [];
  for (const item of items) {
    let best = -1;
    for (const k of keys) {
      const v = item[k];
      if (v == null) continue;
      const s = fuzzyScore(q, v);
      if (s > best) best = s;
    }
    if (best > -1) scored.push({ item, score: best });
  }
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, limit || 50);
}
"""


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------
# Composed with str.replace (not str.format), so CSS/JS braces need no escaping.
# Placeholders: @@TITLE@@ @@ENGINE@@ @@APP@@ @@FLOWSTYLE@@ @@FLOWSCRIPT@@ @@GRAPHDATA@@

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

select.tb-btn {
  padding: 4px 6px;
  min-width: 130px;
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
.node { cursor: pointer; }
.node .shape { stroke-width: 0; }
.node .nlabel { font-size: 11px; font-weight: 600; fill: #1e1e1e; pointer-events: none; }
.node.external .shape { fill-opacity: 0.55; stroke: #8a8aa6; stroke-width: 1px; stroke-dasharray: 4 3; }
.node.external .nlabel { fill: #c8c8d8; font-style: italic; font-weight: 400; }
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
</style>
</head>
<body>

<div id="toolbar">
  <span id="title">📊 @@TITLE@@</span>
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

<script>
@@ENGINE@@
</script>

<script>
@@APP@@
</script>

<script>
@@FLOWSCRIPT@@
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Main call-graph application script (built on GraphView)
# ---------------------------------------------------------------------------

APP_SCRIPT = r"""
// ── Data ──────────────────────────────────────────────────────────────────
const GRAPH_DATA = @@GRAPHDATA@@;

// ── Graph engine init ───────────────────────────────────────────────────────
const gv = new GraphView(document.getElementById('cy'), {
  nodes: GRAPH_DATA.nodes,
  edges: GRAPH_DATA.edges,
  nodeClasses: (n) => n.language + (n.language === 'external' ? ' external' : ''),
  shapeOf: (n) => (n.language === 'external' ? 'round-tag' : 'round-rectangle'),
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

  document.getElementById('stat-selection').textContent = `Selected: ${data.qualified_name}`;
  updateFlowBtn();
}

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


# ---------------------------------------------------------------------------
# Flowchart ("block scheme") view — CSS + JS injected via plain placeholders so
# we don't have to brace-escape this code.
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

/* Flowchart node shapes (fills come from semantic classes, not data.color). */
#flow-cy .nlabel { font-family: 'Consolas', 'Courier New', monospace; font-size: 10px; font-weight: 400; fill: #1e1e1e; }
.node.flow-process .shape   { fill: #9cdcfe; }
.node.flow-decision .shape  { fill: #dcdcaa; }
.node.flow-switch .shape    { fill: #dcdcaa; }
.node.flow-loop .shape      { fill: #c586c0; }
.node.flow-entry .shape     { fill: #4ec9b0; }
.node.flow-entry .nlabel    { fill: #10231f; font-weight: 700; }
.node.flow-exit .shape      { fill: #f48771; }
.node.flow-exit .nlabel     { fill: #2a0f0a; font-weight: 700; }
.node.flow-jump .shape      { fill: #ce9178; }
.node.flow-return .shape    { fill: #f48771; }
.node.flow-throw .shape     { fill: #f44747; }
.node.flow-throw .nlabel    { fill: #ffffff; }
.node.flow-break .shape     { fill: #d7ba7d; }
.node.flow-continue .shape  { fill: #d7ba7d; }
.node.flow-try .shape       { fill: #608b4e; }
.node.flow-try .nlabel      { fill: #ffffff; }
.node.flow-connector .shape { fill: #7878b8; }

/* Flowchart edges. */
.edge.flow-yes      { stroke: #4ec9b0; }
.edge.flow-no       { stroke: #f48771; }
.edge.flow-loopback { stroke: #c586c0; stroke-dasharray: 6 4; }
.edge.flow-catch    { stroke: #f44747; stroke-dasharray: 6 4; }
.edge.flow-jumpedge { stroke-dasharray: 6 4; }
.edge-label.flow-yes   { fill: #7fe0cd; }
.edge-label.flow-no    { fill: #f4a791; }
.edge-label.flow-case  { fill: #dcdcaa; }
.edge-label.flow-catch { fill: #f48a8a; }
"""

FLOW_SCRIPT = r"""
(function () {
  const flowView  = document.getElementById('flow-view');
  const flowTitle = document.getElementById('flow-title');
  const btnFlow   = document.getElementById('btn-flow');
  let flowGv = null;
  let uid = 0;
  const nid = () => 'f' + (uid++);

  // ── Convert a structured flow tree into engine elements ───────────────────
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

  function openFlow(data) {
    if (!data || !data.flow || !data.flow.length) return;
    uid = 0;
    const els = buildElements(data.flow);
    flowTitle.textContent = (data.qualified_name || data.name) + '()';
    flowView.classList.add('open');   // make #flow-cy visible before measuring
    if (flowGv) { flowGv.destroy(); flowGv = null; }
    flowGv = new GraphView(document.getElementById('flow-cy'), {
      nodes: els.nodes,
      edges: els.edges,
      edgeLabelOf: (e) => e.label,
    });
    flowGv.layout('dagre', { rankDir: 'TB', nodeSep: 26, rankSep: 50 });
  }
  function closeFlow() { flowView.classList.remove('open'); }

  // ── Wiring ────────────────────────────────────────────────────────────────
  btnFlow.addEventListener('click', () => { if (typeof currentData !== 'undefined' && currentData) openFlow(currentData); });
  document.getElementById('flow-back').addEventListener('click', closeFlow);
  document.getElementById('flow-fit').addEventListener('click', () => { if (flowGv) flowGv.fit(30); });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && flowView.classList.contains('open')) { e.stopPropagation(); closeFlow(); }
  }, true);
})();
"""


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def render(graph: CallGraph, title: str) -> str:
    """Render a CallGraph to a fully self-contained, dependency-free HTML string."""
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

    # Token replacement (not str.format) so embedded CSS/JS braces need no
    # escaping. Scripts are injected first; the (escaped) graph data goes last
    # to fill the @@GRAPHDATA@@ placeholder carried in by APP_SCRIPT.
    out = HTML_TEMPLATE
    out = out.replace("@@ENGINE@@", ENGINE_SCRIPT)
    out = out.replace("@@APP@@", APP_SCRIPT)
    out = out.replace("@@FLOWSTYLE@@", FLOW_STYLE)
    out = out.replace("@@FLOWSCRIPT@@", FLOW_SCRIPT)
    out = out.replace("@@TITLE@@", html.escape(title, quote=True))
    out = out.replace("@@GRAPHDATA@@", graph_data_json)
    return out
