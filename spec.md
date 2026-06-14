This is a CLI Python script which generates an interactive, self-contained HTML call graph from source code. The main goal is to see the whole algorithm flow — not only the "happy path" but step-by-step the entire control structure.

- We generate a single, fully independent HTML file. It can be sent to anyone and opened in any browser without a server or internet connection. The file has **no external dependencies**: it embeds its own small SVG graph engine (no CDN libraries, no network fetch at render time).
- The visualization is rendered by a hand-written SVG engine (`renderer.py` → `ENGINE_SCRIPT`) providing the graph data model, layered ("hierarchical"), force-directed and concentric layouts, pan/zoom/drag, fuzzy search and the flowchart renderer. Graph nodes are functions/methods, edges are calls.
- Each node carries metadata: file path (relative when possible), class name if applicable, language, line range, full source code, and a structured control-flow tree for flowchart rendering.
- **Flow model (rooted, downstream view).** The tool visualizes *flows*, not the full bidirectional call graph. The path the user points at defines the **scope** (the single file, or every file under a directory). The graph is pruned to what is reachable *from* the scope via call (callee) edges, so callers outside the scope — e.g. tests that call into the entry file — are dropped; what remains is the downstream flow. Within the pruned graph:
  - **entrypoints** are scope functions that nothing in the graph calls — the roots where a flow starts (if the whole scope is cyclic, all scope nodes are treated as roots). They are styled distinctly and listed in a **Flows ▾** menu.
  - each node gets a **depth** = shortest call-distance from any entrypoint, giving a deterministic order to walk the flow.
  - selecting a flow (from the menu, or "Isolate downstream flow" in the info panel) dims everything outside that entrypoint's downstream subtree, so one rooted flow is shown at a time.
- **LLM-enrichment slots (forward-looking).** The deterministic graph is the reliable substrate; a later, separate pass walks each flow (root → callees, in depth order) and fills per-node `summary`/`description` and per-edge `semantic_label`. Each node also carries a line-independent `stable_key` (`<relative_file>::<qualified_name>`) so generated annotations survive edits that shift line numbers. These slots are empty until enriched and the renderer surfaces them when present.
- Edge confidence levels:
  - **definite** — exactly one function in the parsed set matches the call name
  - **possible** — multiple functions share the call name (shown as dashed edges)
  - **external** — no match in the parsed set (stdlib / builtin / third-party)
- We support as many languages as possible via tree-sitter. Currently: Python, JavaScript (incl. JSX), TypeScript (incl. TSX), Go, Java, C/C++, PHP.
- Input can be a single file or a directory. Directories are traversed recursively, adding more root nodes if files are unconnected. Common build/cache/vendor folders are automatically ignored.
- On the page: fuzzy search input, layout switcher (hierarchical LR/TB, force-directed, concentric), zoom controls, toggle buttons for possible edges and external calls, clickable info panel with callers/callees list and source code.
- **Flowchart ("block scheme") view** — any function with extractable control flow can be opened as a top-to-bottom flowchart showing: process steps, decision diamonds for `if`/`switch`/`match`, loop hexagons with back-edges, and distinct jump nodes for `return`/`break`/`continue`/`throw` plus `try`/`catch`/`finally`. Works for all supported languages.

1. How to run:
   ```bash
   python graph.py <file_or_directory> -o graph.html
   python graph.py src/main.py -o out.html
   python graph.py ./my_project -o out.html
   ```
   Flags:
   - `-o, --output` — output HTML file path (default: `graph.html`)
   - `--no-possible` — exclude low-confidence (ambiguous) call edges
   - `--no-external` — exclude external/stdlib/builtin calls, showing only in-project functions
