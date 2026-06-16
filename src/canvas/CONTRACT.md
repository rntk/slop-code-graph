# Canvas view — Python ↔ JS data contract (POC)

The Python pipeline (`src/canvas/pipeline.py`) produces a `canvas` dict that is
embedded into the generated HTML under `GRAPH_DATA.canvas` (see
`src/renderer/render.py`). The browser-side asset (`src/renderer/assets/canvas.py`)
reads exactly this shape. **Neither side may change a field without the other.**

```jsonc
{
  // The whole flow glued into one document, ONE entry per tagged unit {N}.
  // index === unit number (0-based). Each entry is one physical line.
  "lines": ["=== payment.py :: process_payment (L13-42) ===", "def process_payment(...):", "    ..."],

  // Parallel array to `lines` (same length, same index).
  "lineMeta": [
    {
      "kind": "header" | "code",        // header = synthetic per-function separator line
      "nodeId": "src/..py::fn::12:4",   // graph node id this line belongs to ("" for nothing)
      "stableKey": "src/..py::fn",      // node stable_key ("" if none)
      "relativeFile": "src/..py",        // ("" for header-only context)
      "qualifiedName": "Class.method",
      "fileLine": 13                      // original 1-based line number in the source file (0 if N/A)
    }
  ],

  // Topical sections produced by the LLM topic-ranges split, in document order.
  "topics": [
    {
      "path": "Subsystem>Concern>Specific",  // full ">"-joined hierarchical label
      "name": "Specific",                      // last path segment
      "level": 3,                              // number of path segments
      "ranges": [{ "start": 0, "end": 12 }],  // 0-based inclusive unit ranges (continuous coverage overall)
      "lineNumbers": [1, 2, 3],                // 1-based unit numbers covered (convenience, derived from ranges)
      "summary": "Terse description of what this code section does."  // may be "" (NO_SUMMARY)
    }
  ],

  "stats": { "lineCount": 123, "topicCount": 8 }
}
```

Invariants the JS may rely on:
- `lines.length === lineMeta.length === stats.lineCount`.
- Topic `ranges` across all topics give continuous, non-overlapping coverage of
  `[0, lineCount-1]` (guaranteed by the topic parser's repair step).
- `topics` are ordered by their first unit index ascending.
- The hierarchy rail is derived **structurally** on the JS side from `path`
  segments (parents = label + aggregated unit span; leaves carry `summary`).
  Python only emits leaf topics + their summaries.
