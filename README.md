# Call Graph Generator

Generate an interactive, self-contained HTML call-graph from source code.
Supports **Python, JavaScript, TypeScript, TSX, Go, Java, C/C++, PHP** via tree-sitter ASTs.

## Docker (recommended)

### Build the image

```bash
docker build -t callgraph .
```

The container runs as a non-root user (`uid=1000`). If the output file ends up owned by the wrong user, pass `--user $(id -u):$(id -g)` to match your host user:

```bash
docker run --rm --user $(id -u):$(id -g) \
  -v /path/to/your/project:/code \
  callgraph /code -o /code/graph.html
```

### Analyze a project

Mount your codebase at `/code` and write the output to the same directory:

```bash
docker run --rm \
  -v /path/to/your/project:/code \
  callgraph /code -o /code/graph.html
```

Open `graph.html` in any browser — it is fully self-contained (no server needed).

### Analyze a single file

```bash
docker run --rm \
  -v /path/to/your/project:/code \
  callgraph /code/main.py -o /code/graph.html
```

### Write output to a different location

```bash
docker run --rm \
  -v /path/to/your/project:/code \
  -v /tmp:/out \
  callgraph /code -o /out/graph.html
```

### Exclude low-confidence edges

```bash
docker run --rm \
  -v /path/to/your/project:/code \
  callgraph /code -o /code/graph.html --no-possible
```

### Exclude external / stdlib calls

By default, calls to functions that aren't defined in the analyzed code
(builtins, the standard library, third-party packages) are shown as muted
*external* nodes so the full control flow is visible. Pass `--no-external` to
show only your own functions:

```bash
docker run --rm \
  -v /path/to/your/project:/code \
  callgraph /code -o /code/graph.html --no-external
```

---

## Local usage (Python 3.12+)

```bash
pip install -r requirements.txt
python graph.py /path/to/project -o graph.html
python graph.py src/main.py -o graph.html
```

---

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `path` | *(required)* | File or directory to analyze |
| `-o / --output` | `graph.html` | Output HTML file path |
| `--no-possible` | off | Drop ambiguous (dashed) call edges |
| `--no-external` | off | Drop external/stdlib/builtin call nodes (show only in-project functions) |

---

## Supported languages

| Language | Extensions |
|----------|-----------|
| Python | `.py` |
| JavaScript | `.js .mjs .cjs .jsx` |
| TypeScript | `.ts` |
| TSX | `.tsx` |
| Go | `.go` |
| Java | `.java` |
| C / C++ | `.c .cpp .cc .cxx .h .hpp .hxx .c++` |
| PHP | `.php` |

Directories named `.git`, `node_modules`, `__pycache__`, `vendor`, `dist`, `build`, `venv`, `.venv` are skipped automatically.

---

## HTML features

- **Zoomable/pannable** canvas
- **Click** a node to highlight its callers and callees
- **Fuzzy search** box to jump to any function
- **Layout switcher** — dagre left-to-right (default), top-to-bottom, cose, concentric
- **Dashed edges** = low-confidence matches (multiple functions share the same name); toggle with the *Possible edges* button
- **External nodes** = stdlib/builtin/third-party calls (muted, dashed outline) so the whole algorithm is visible; toggle with the *External calls* button
- **Color-coded** by language
