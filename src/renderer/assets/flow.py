"""Flowchart ("block scheme") view assets.

CSS + JS injected via plain placeholders (@@FLOWSTYLE@@ / @@FLOWSCRIPT@@)
so the renderer does not have to brace-escape the embedded code.
"""

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
