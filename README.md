# Call Graph Generator

Generate an interactive, self-contained HTML call-graph from source code.
Supports **Python, JavaScript, TypeScript, TSX, Go, Java, C/C++, PHP** via tree-sitter ASTs.

## Docker (recommended)

### Build the image

```bash
docker build -t callgraph .
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
- **Dashed edges** = low-confidence matches (multiple functions share the same name); toggle with the *Hide possible* button
- **Color-coded** by language
