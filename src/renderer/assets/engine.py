"""Embedded SVG graph engine (GraphView + layouts + fuzzy search).

This is injected verbatim into the generated HTML. It must not contain the
literal sequence "</" (would close the <script> early) or the "@@...@@"
placeholder tokens used by the renderer.
"""

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
    // Grouping: on by default when the caller supplies a groupOf accessor.
    // Grouped layouts fill _groupBoxes with absolute container rects.
    this.grouping = !!(this.o && this.o.groupOf);
    this._groupBoxes = [];
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
    // Groups (file containers) sit behind edges and nodes so functions render
    // on top of their file box.
    this.gLayer = svgEl('g', { class: 'groups' });
    this.eLayer = svgEl('g', { class: 'edges' });
    this.nLayer = svgEl('g', { class: 'nodes' });
    this.vp.appendChild(this.gLayer);
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
      let bb = txt.getBBox();
      tw = bb.width; th = bb.height;
      if (tw === 0 || th === 0) {
        let maxWidth = 0;
        lines.forEach((ln, idx) => {
          const charW = idx === 0 ? 7.2 : 6.5;
          const w = ln.length * charW;
          if (w > maxWidth) maxWidth = w;
        });
        tw = maxWidth;
        th = lines.length * 14;
      }
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

  _resolveId(id) {
    return (this.o.endpointOf ? (this.o.endpointOf(id) || id) : id);
  }

  setNodeLabel(id, label) {
    const n = this.N.get(id);
    if (!n) return;
    const g = n.g;
    const shape = this.o.shapeOf ? this.o.shapeOf(n.data) : shapeFromClasses(n.cls);
    const hasText = String(label) !== '' && shape !== 'ellipse';
    let txt = g.querySelector('text.nlabel');
    if (!hasText) {
      if (txt) txt.remove();
      return;
    }
    if (!txt) {
      txt = svgEl('text', { class: 'nlabel', 'text-anchor': 'middle', 'dominant-baseline': 'central' });
      g.appendChild(txt);
    }
    while (txt.firstChild) txt.removeChild(txt.firstChild);
    const lines = String(label).split('\n');
    const lh = 12;
    lines.forEach((ln, i) => {
      const ts = svgEl('tspan', { x: 0 });
      ts.setAttribute('dy', i === 0 ? -(lines.length - 1) * lh / 2 : lh);
      ts.textContent = ln;
      txt.appendChild(ts);
    });
    const prevDisplay = g.style.display;
    if (n.hidden) {
      g.style.display = '';
    }
    let bb = txt.getBBox();
    if (bb.width === 0 || bb.height === 0) {
      let maxWidth = 0;
      lines.forEach((ln, idx) => {
        const charW = idx === 0 ? 7.2 : 6.5;
        const w = ln.length * charW;
        if (w > maxWidth) maxWidth = w;
      });
      bb = {
        width: maxWidth,
        height: lines.length * 14
      };
    }
    if (n.hidden) {
      g.style.display = prevDisplay;
    }
    const sz = sizeForShape(shape, bb.width, bb.height);
    const fill = this.o.fillOf ? this.o.fillOf(n.data) : null;
    const newShp = shapeEl(shape, sz.w, sz.h);
    if (fill) newShp.style.fill = fill;
    g.replaceChild(newShp, n.shp);
    n.shp = newShp;
    n.w = sz.w;
    n.h = sz.h;
  }

  _redrawEdge(eo) {
    const sid = this._resolveId(eo.data.source);
    const tid = this._resolveId(eo.data.target);
    if (sid === tid) {
      eo.path.style.display = 'none';
      if (eo.lblEl) { eo.lblEl.style.display = 'none'; eo.lblBg.style.display = 'none'; }
      return;
    }
    const s = this.N.get(sid), t = this.N.get(tid);
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
    this._redrawGroups();
  }

  // Render the grouping boxes computed by grouped layouts. Rebuilt from
  // scratch each time so toggling grouping / re-running a flat layout simply
  // clears them (empty _groupBoxes -> empty layer).
  _redrawGroups() {
    const layer = this.gLayer;
    while (layer.firstChild) layer.removeChild(layer.firstChild);
    (this._groupBoxes || []).forEach((b) => {
      const cls = 'gv-group' + (b.depth != null ? ' depth-' + b.depth : '');
      const g = svgEl('g', { class: cls });
      if (b.key != null) g.setAttribute('data-group-key', b.key);
      const rect = svgEl('rect', {
        x: b.x, y: b.y, width: b.w, height: b.h, rx: 10, ry: 10, class: 'gv-group-box',
      });
      if (b.color) rect.style.stroke = b.color;
      g.appendChild(rect);
      const label = svgEl('text', {
        x: b.x + 12, y: b.y + 16, class: 'gv-group-label',
      });
      label.textContent = b.label;
      if (b.key != null) label.setAttribute('data-group-key', b.key);
      if (b.color) label.style.fill = b.color;
      g.appendChild(label);
      layer.appendChild(g);
    });
  }

  setGrouping(on) {
    this.grouping = !!on && !!this.o.groupOf;
  }

  _groupPath(id) {
    if (this.o.groupPathOf) {
      const p = this.o.groupPathOf(this.N.get(id).data);
      if (Array.isArray(p)) return p.map((x) => String(x || '').trim()).filter(Boolean);
      if (p == null || p === '') return [];
      return [String(p)];
    }
    const k = this.o.groupOf ? this.o.groupOf(this.N.get(id).data) : null;
    return (k == null || k === '') ? [] : [String(k)];
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
    // File grouping (when a groupOf accessor is supplied and enabled) lays the
    // graph out as nested boxes; see _dagreGrouped. Otherwise lay every visible
    // node out in one flat hierarchy.
    if (this.grouping && this.o.groupOf) {
      this._dagreGrouped(rankDir, nodeSep, rankSep);
      return;
    }
    this._groupBoxes = [];
    const all = [...this.N.keys()].filter((i) => !this.N.get(i).hidden);
    if (!all.length) return;
    const idset = new Set(all);
    const E = this._visibleEdges(all);

    const pos = this._layoutDagre(all, E, (id) => this.N.get(id), rankDir, nodeSep, rankSep);
    all.forEach((id) => { const n = this.N.get(id), p = pos.get(id); n.x = p.x; n.y = p.y; });
  }

  // Pure layered (dagre-style) layout over an arbitrary node/edge set. Returns a
  // Map id -> {x, y} of node *centres*. ``sizeOf(id)`` yields {w, h} for a node,
  // letting the same routine lay out real nodes or synthetic file-box meta-nodes.
  _layoutDagre(all, E, sizeOf, rankDir, nodeSep, rankSep) {
    const result = new Map();
    if (!all.length) return result;

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
      layers[r].forEach((id) => { const n = sizeOf(id); mx = Math.max(mx, horizontal ? n.w : n.h); });
      mainC[r] = acc + mx / 2;
      acc += mx + rankSep;
    }
    const cross = new Map();
    layers.forEach((L) => {
      let c = 0;
      L.forEach((id, i) => {
        const n = sizeOf(id);
        const cs = horizontal ? n.h : n.w;
        if (i > 0) c += nodeSep;
        c += cs / 2; cross.set(id, c); c += cs / 2;
      });
      const shift = -c / 2;
      L.forEach((id) => cross.set(id, cross.get(id) + shift));
    });

    // Light centering refinement: pull each node toward neighbour barycenter,
    // then push apart to remove overlaps. Improves straightness of long paths.
    const sizeCross = (id) => { const n = sizeOf(id); return horizontal ? n.h : n.w; };
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
      if (horizontal) result.set(id, { x: mainC[rank.get(id)], y: cross.get(id) });
      else result.set(id, { x: cross.get(id), y: mainC[rank.get(id)] });
    });
    return result;
  }

  // Grouped (nested) hierarchical layout. Each file becomes a container box:
  //   1. lay out each file's own nodes internally (intra-file edges only),
  //      yielding per-file positions and a padded box size;
  //   2. treat every file box — plus each ungrouped node (e.g. external) — as a
  //      meta-node and lay *those* out with the same routine, using cross-file
  //      edges; this spaces the boxes so they never overlap;
  //   3. translate each file's internal positions into its box's final slot.
  // Because a node's relative position is clamped within its box's padding, the
  // function nodes are always fully contained by their file box.
  _dagreGrouped(rankDir, nodeSep, rankSep) {
    if (this.o.groupPathOf) {
      this._hierarchicalGroupedLayout('dagre', { rankDir, nodeSep, rankSep });
      return;
    }
    const PAD = 16;        // inner margin around the nodes inside a box
    const HEADER = 26;     // extra top space for the file label
    const all = [...this.N.keys()].filter((i) => !this.N.get(i).hidden);
    if (!all.length) { this._groupBoxes = []; return; }

    const keyOf = (id) => this.o.groupOf(this.N.get(id).data);
    const groups = new Map();   // groupKey -> [ids]
    const loners = [];          // ungrouped node ids (own meta-node)
    all.forEach((id) => {
      const k = keyOf(id);
      if (k == null || k === '') { loners.push(id); return; }
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(id);
    });

    // All visible, non-self edges — reused for both intra- and inter-group passes.
    const E = [];
    const idset = new Set(all);
    this.E.forEach((e) => {
      if (e.hidden) return;
      const s = e.data.source, t = e.data.target;
      if (s !== t && idset.has(s) && idset.has(t)) E.push([s, t]);
    });

    // 1. Lay each group out internally; record per-node relative centres + box size.
    const intra = new Map();    // id -> {x, y} relative to its box top-left
    const metaSize = new Map(); // metaId -> {w, h}
    const metaColor = new Map();
    const metaLabel = new Map();
    groups.forEach((gids, key) => {
      const gset = new Set(gids);
      const gE = E.filter(([s, t]) => gset.has(s) && gset.has(t));
      const gpos = this._layoutDagre(gids, gE, (id) => this.N.get(id), rankDir, nodeSep, rankSep);
      let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
      gids.forEach((id) => {
        const n = this.N.get(id), p = gpos.get(id);
        minX = Math.min(minX, p.x - n.w / 2); maxX = Math.max(maxX, p.x + n.w / 2);
        minY = Math.min(minY, p.y - n.h / 2); maxY = Math.max(maxY, p.y + n.h / 2);
      });
      gids.forEach((id) => {
        const p = gpos.get(id);
        intra.set(id, { x: p.x - minX + PAD, y: p.y - minY + PAD + HEADER });
      });
      metaSize.set(key, { w: (maxX - minX) + PAD * 2, h: (maxY - minY) + PAD * 2 + HEADER });
      // Box accent colour follows the file's dominant language colour.
      const first = this.N.get(gids[0]);
      metaColor.set(key, first && first.data ? first.data.color : null);
      metaLabel.set(key, key);
    });
    loners.forEach((id) => {
      const n = this.N.get(id);
      metaSize.set(id, { w: n.w, h: n.h });
    });

    // 2. Inter-group meta layout.
    const metaOf = (id) => { const k = keyOf(id); return (k == null || k === '') ? id : k; };
    const metaIds = [...groups.keys(), ...loners];
    const metaSeen = new Set();
    const metaE = [];
    E.forEach(([s, t]) => {
      const ms = metaOf(s), mt = metaOf(t);
      if (ms === mt) return;
      const k = ms + '##' + mt;
      if (metaSeen.has(k)) return;
      metaSeen.add(k);
      metaE.push([ms, mt]);
    });
    const mpos = this._layoutDagre(
      metaIds, metaE, (id) => metaSize.get(id), rankDir, nodeSep + 24, rankSep + 24,
    );

    // 3. Place real nodes; record absolute box rects for _redrawGroups.
    const boxes = [];
    groups.forEach((gids, key) => {
      const c = mpos.get(key), sz = metaSize.get(key);
      const x0 = c.x - sz.w / 2, y0 = c.y - sz.h / 2;
      gids.forEach((id) => {
        const rel = intra.get(id), n = this.N.get(id);
        n.x = x0 + rel.x; n.y = y0 + rel.y;
      });
      boxes.push({ x: x0, y: y0, w: sz.w, h: sz.h, label: metaLabel.get(key), key, color: metaColor.get(key), depth: 0 });
    });
    loners.forEach((id) => {
      const c = mpos.get(id), n = this.N.get(id);
      n.x = c.x; n.y = c.y;
    });
    this._groupBoxes = boxes;
  }

  _cose() {
    if (this.grouping && this.o.groupOf) {
      this._groupedLayout('cose');
      return;
    }
    this._groupBoxes = [];
    const ids = [...this.N.keys()].filter((i) => !this.N.get(i).hidden);
    const edges = this._visibleEdges(ids);
    const pos = this._layoutCose(ids, edges);
    ids.forEach((id) => { const p = pos.get(id), nn = this.N.get(id); nn.x = p.x; nn.y = p.y; });
  }

  _layoutCose(ids, edges) {
    const pos = new Map();
    const n = ids.length;
    if (!n) return pos;
    const R = Math.max(200, n * 28);
    ids.forEach((id, i) => { const a = 2 * Math.PI * i / n; pos.set(id, { x: Math.cos(a) * R, y: Math.sin(a) * R }); });
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
    return pos;
  }

  _concentric() {
    if (this.grouping && this.o.groupOf) {
      this._groupedLayout('concentric');
      return;
    }
    this._groupBoxes = [];
    const ids = [...this.N.keys()].filter((i) => !this.N.get(i).hidden);
    const edges = this._visibleEdges(ids);
    const pos = this._layoutConcentric(ids, edges);
    ids.forEach((id) => { const p = pos.get(id), nn = this.N.get(id); nn.x = p.x; nn.y = p.y; });
  }

  _layoutConcentric(ids, edges) {
    const pos = new Map();
    if (!ids.length) return pos;
    const deg = new Map(ids.map((i) => [i, 0]));
    edges.forEach(([s, t]) => {
      if (deg.has(s)) deg.set(s, deg.get(s) + 1);
      if (deg.has(t)) deg.set(t, deg.get(t) + 1);
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
        pos.set(id, {
          x: r === 0 ? 0 : Math.cos(a) * r,
          y: r === 0 ? 0 : Math.sin(a) * r,
        });
      });
    });
    return pos;
  }

  _visibleEdges(ids) {
    const idset = new Set(ids);
    const E = [];
    const seen = new Set();
    this.E.forEach((e) => {
      if (e.hidden) return;
      const s = this._resolveId(e.data.source);
      const t = this._resolveId(e.data.target);
      if (s === t || !idset.has(s) || !idset.has(t)) return;
      const key = s + '##' + t;
      if (seen.has(key)) return;
      seen.add(key);
      E.push([s, t]);
    });
    return E;
  }

  _layoutByMode(mode, ids, edges) {
    return mode === 'concentric'
      ? this._layoutConcentric(ids, edges)
      : this._layoutCose(ids, edges);
  }

  _separateMetaBoxes(metaIds, pos, sizeOf) {
    const GAP = 42;
    for (let it = 0; it < 80; it++) {
      let moved = false;
      for (let a = 0; a < metaIds.length; a++) {
        for (let b = a + 1; b < metaIds.length; b++) {
          const ia = metaIds[a], ib = metaIds[b];
          const pa = pos.get(ia), pb = pos.get(ib);
          const sa = sizeOf.get(ia), sb = sizeOf.get(ib);
          const minDx = (sa.w + sb.w) / 2 + GAP;
          const minDy = (sa.h + sb.h) / 2 + GAP;
          let dx = pb.x - pa.x, dy = pb.y - pa.y;
          if (Math.abs(dx) >= minDx || Math.abs(dy) >= minDy) continue;
          if (Math.abs(dx) / minDx < Math.abs(dy) / minDy) {
            const push = (minDx - Math.abs(dx)) / 2;
            const dir = dx < 0 ? -1 : 1;
            pa.x -= dir * push; pb.x += dir * push;
          } else {
            const push = (minDy - Math.abs(dy)) / 2;
            const dir = dy < 0 ? -1 : 1;
            pa.y -= dir * push; pb.y += dir * push;
          }
          moved = true;
        }
      }
      if (!moved) break;
    }
  }

  _groupedLayout(mode) {
    if (this.o.groupPathOf) {
      this._hierarchicalGroupedLayout(mode, {});
      return;
    }
    const PAD = 16;
    const HEADER = 26;
    const all = [...this.N.keys()].filter((i) => !this.N.get(i).hidden);
    if (!all.length) { this._groupBoxes = []; return; }

    const keyOf = (id) => this.o.groupOf(this.N.get(id).data);
    const groups = new Map();
    const loners = [];
    all.forEach((id) => {
      const k = keyOf(id);
      if (k == null || k === '') { loners.push(id); return; }
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(id);
    });

    const E = this._visibleEdges(all);
    const intra = new Map();
    const metaSize = new Map();
    const metaColor = new Map();
    const metaLabel = new Map();

    groups.forEach((gids, key) => {
      const gset = new Set(gids);
      const gE = E.filter(([s, t]) => gset.has(s) && gset.has(t));
      const gpos = this._layoutByMode(mode, gids, gE);
      let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
      gids.forEach((id) => {
        const n = this.N.get(id), p = gpos.get(id);
        minX = Math.min(minX, p.x - n.w / 2); maxX = Math.max(maxX, p.x + n.w / 2);
        minY = Math.min(minY, p.y - n.h / 2); maxY = Math.max(maxY, p.y + n.h / 2);
      });
      gids.forEach((id) => {
        const p = gpos.get(id);
        intra.set(id, { x: p.x - minX + PAD, y: p.y - minY + PAD + HEADER });
      });
      metaSize.set(key, { w: (maxX - minX) + PAD * 2, h: (maxY - minY) + PAD * 2 + HEADER });
      const first = this.N.get(gids[0]);
      metaColor.set(key, first && first.data ? first.data.color : null);
      metaLabel.set(key, key);
    });
    loners.forEach((id) => {
      const n = this.N.get(id);
      metaSize.set(id, { w: n.w, h: n.h });
    });

    const metaOf = (id) => { const k = keyOf(id); return (k == null || k === '') ? id : k; };
    const metaIds = [...groups.keys(), ...loners];
    const metaSeen = new Set();
    const metaE = [];
    E.forEach(([s, t]) => {
      const ms = metaOf(s), mt = metaOf(t);
      if (ms === mt) return;
      const k = ms + '##' + mt;
      if (metaSeen.has(k)) return;
      metaSeen.add(k);
      metaE.push([ms, mt]);
    });

    const mpos = this._layoutByMode(mode, metaIds, metaE);
    this._separateMetaBoxes(metaIds, mpos, metaSize);

    const boxes = [];
    groups.forEach((gids, key) => {
      const c = mpos.get(key), sz = metaSize.get(key);
      const x0 = c.x - sz.w / 2, y0 = c.y - sz.h / 2;
      gids.forEach((id) => {
        const rel = intra.get(id), n = this.N.get(id);
        n.x = x0 + rel.x; n.y = y0 + rel.y;
      });
      boxes.push({ x: x0, y: y0, w: sz.w, h: sz.h, label: metaLabel.get(key), key, color: metaColor.get(key), depth: 0 });
    });
    loners.forEach((id) => {
      const c = mpos.get(id), n = this.N.get(id);
      n.x = c.x; n.y = c.y;
    });
    this._groupBoxes = boxes;
  }

  _layoutForMode(mode, ids, edges, sizeOf, opts) {
    opts = opts || {};
    if (mode === 'dagre') {
      return this._layoutDagre(
        ids, edges, sizeOf,
        opts.rankDir || 'TB',
        opts.nodeSep || 34,
        opts.rankSep || 90,
      );
    }
    if (mode === 'concentric') return this._layoutConcentric(ids, edges);
    return this._layoutCose(ids, edges);
  }

  _hierarchicalGroupedLayout(mode, opts) {
    const PAD = 18;
    const HEADER = 28;
    const all = [...this.N.keys()].filter((i) => !this.N.get(i).hidden);
    if (!all.length) { this._groupBoxes = []; return; }

    const paths = new Map();
    all.forEach((id) => paths.set(id, this._groupPath(id)));
    const E = this._visibleEdges(all);
    const boxes = [];

    const cluster = (ids, level, prefix) => {
      const childMap = new Map();
      const local = [];
      ids.forEach((id) => {
        const p = paths.get(id) || [];
        if (p.length > level) {
          const seg = p[level];
          if (!childMap.has(seg)) childMap.set(seg, []);
          childMap.get(seg).push(id);
        } else {
          local.push(id);
        }
      });

      if (!childMap.size) {
        const innerEdges = E.filter(([s, t]) => ids.includes(s) && ids.includes(t));
        const pos = this._layoutForMode(mode, ids, innerEdges, (id) => this.N.get(id), opts);
        let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
        ids.forEach((id) => {
          const n = this.N.get(id), p = pos.get(id) || { x: 0, y: 0 };
          minX = Math.min(minX, p.x - n.w / 2); maxX = Math.max(maxX, p.x + n.w / 2);
          minY = Math.min(minY, p.y - n.h / 2); maxY = Math.max(maxY, p.y + n.h / 2);
        });
        if (!ids.length) { minX = minY = 0; maxX = maxY = 1; }
        const nodePos = new Map();
        ids.forEach((id) => {
          const p = pos.get(id) || { x: 0, y: 0 };
          nodePos.set(id, { x: p.x - minX + PAD, y: p.y - minY + PAD + HEADER });
        });
        return {
          w: Math.max(80, (maxX - minX) + PAD * 2),
          h: Math.max(54, (maxY - minY) + PAD * 2 + HEADER),
          nodePos,
          childBoxes: [],
        };
      }

      const childLayouts = new Map();
      const metaIds = [];
      const metaSize = new Map();
      childMap.forEach((childIds, seg) => {
        const key = prefix.concat(seg).join('>');
        const child = cluster(childIds, level + 1, prefix.concat(seg));
        childLayouts.set(seg, child);
        metaIds.push(key);
        metaSize.set(key, { w: child.w, h: child.h });
      });
      local.forEach((id) => {
        metaIds.push(id);
        const n = this.N.get(id);
        metaSize.set(id, { w: n.w, h: n.h });
      });

      const idToMeta = (id) => {
        const p = paths.get(id) || [];
        if (p.length > level) return prefix.concat(p[level]).join('>');
        return id;
      };
      const metaSeen = new Set();
      const metaE = [];
      E.forEach(([s, t]) => {
        if (!ids.includes(s) || !ids.includes(t)) return;
        const ms = idToMeta(s), mt = idToMeta(t);
        if (ms === mt) return;
        const k = ms + '##' + mt;
        if (metaSeen.has(k)) return;
        metaSeen.add(k);
        metaE.push([ms, mt]);
      });
      const metaOpts = mode === 'dagre'
        ? { rankDir: opts.rankDir || 'TB', nodeSep: (opts.nodeSep || 34) + 24, rankSep: (opts.rankSep || 90) + 24 }
        : opts;
      const mpos = this._layoutForMode(mode, metaIds, metaE, (id) => metaSize.get(id), metaOpts);
      if (mode !== 'dagre') this._separateMetaBoxes(metaIds, mpos, metaSize);

      let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
      metaIds.forEach((id) => {
        const p = mpos.get(id) || { x: 0, y: 0 }, sz = metaSize.get(id);
        minX = Math.min(minX, p.x - sz.w / 2); maxX = Math.max(maxX, p.x + sz.w / 2);
        minY = Math.min(minY, p.y - sz.h / 2); maxY = Math.max(maxY, p.y + sz.h / 2);
      });

      const nodePos = new Map();
      const childBoxes = [];
      childMap.forEach((childIds, seg) => {
        const key = prefix.concat(seg).join('>');
        const child = childLayouts.get(seg);
        const c = mpos.get(key) || { x: 0, y: 0 };
        const x0 = c.x - child.w / 2 - minX + PAD;
        const y0 = c.y - child.h / 2 - minY + PAD + HEADER;
        child.nodePos.forEach((p, nid) => nodePos.set(nid, { x: x0 + p.x, y: y0 + p.y }));
        const color = this.o.groupColorOf ? this.o.groupColorOf(key, level) : null;
        childBoxes.push({
          x: x0, y: y0, w: child.w, h: child.h,
          label: this.o.groupLabelOf ? this.o.groupLabelOf(key) : seg,
          key,
          color,
          depth: level,
        });
        child.childBoxes.forEach((b) => childBoxes.push({
          x: x0 + b.x, y: y0 + b.y, w: b.w, h: b.h,
          label: b.label, key: b.key, color: b.color, depth: b.depth,
        }));
      });
      local.forEach((id) => {
        const c = mpos.get(id) || { x: 0, y: 0 };
        nodePos.set(id, { x: c.x - minX + PAD, y: c.y - minY + PAD + HEADER });
      });

      return {
        w: Math.max(100, (maxX - minX) + PAD * 2),
        h: Math.max(64, (maxY - minY) + PAD * 2 + HEADER),
        nodePos,
        childBoxes,
      };
    };

    const root = cluster(all, 0, []);
    root.nodePos.forEach((p, id) => {
      const n = this.N.get(id);
      n.x = p.x; n.y = p.y;
    });
    this._groupBoxes = root.childBoxes;
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
    (this._groupBoxes || []).forEach((b) => {
      minX = Math.min(minX, b.x); maxX = Math.max(maxX, b.x + b.w);
      minY = Math.min(minY, b.y); maxY = Math.max(maxY, b.y + b.h);
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
