"""Control-flow extraction (flowchart / "block scheme" view).

Produces a nested list of statement dicts from a function body. Each
element is one of:
  {"t":"process", "lines":[str,...]}            run of simple statements
  {"t":"if", "cond":str, "then":[...], "else":[...]}
  {"t":"loop", "kind":str, "label":str, "body":[...], "do":bool}
  {"t":"switch", "label":str, "cases":[{"label":str,"body":[...]}]}
  {"t":"try", "body":[...], "handlers":[{"label","body"}], "final":[...]}
  {"t":"jump", "kind":"return|break|continue|throw", "label":str}

The renderer turns this tree into a flowchart graph in the browser.
"""

from __future__ import annotations


class FlowBuilder:
    """Mixin providing structured control-flow extraction.

    LanguageParser subclasses provide the node-type sets (IF_NODE_TYPES etc.)
    and the source-slicing helpers via self. The mixin supplies the
    _build_flow family of methods.
    """

    # ------------------------------------------------------------------
    # Control-flow node-type categories (for the flowchart / "block scheme"
    # view). Defaults cover the common C-family shape (JS/TS/Java/C++);
    # languages with different grammars override the relevant sets below.
    # ------------------------------------------------------------------
    IF_NODE_TYPES: frozenset = frozenset({"if_statement"})
    ELIF_NODE_TYPES: frozenset = frozenset()  # e.g. Python elif_clause
    ELSE_NODE_TYPES: frozenset = frozenset({"else_clause"})
    LOOP_NODE_TYPES: frozenset = frozenset({"for_statement", "while_statement", "do_statement"})
    SWITCH_NODE_TYPES: frozenset = frozenset({"switch_statement", "switch_expression"})
    CASE_NODE_TYPES: frozenset = frozenset(
        {
            "switch_case",
            "switch_default",
            "case_statement",
            "default_statement",
            "switch_block_statement_group",
            "switch_rule",
        }
    )
    TRY_NODE_TYPES: frozenset = frozenset({"try_statement"})
    CATCH_NODE_TYPES: frozenset = frozenset({"catch_clause"})
    FINALLY_NODE_TYPES: frozenset = frozenset({"finally_clause"})
    RETURN_NODE_TYPES: frozenset = frozenset({"return_statement"})
    BREAK_NODE_TYPES: frozenset = frozenset({"break_statement"})
    CONTINUE_NODE_TYPES: frozenset = frozenset({"continue_statement"})
    THROW_NODE_TYPES: frozenset = frozenset({"throw_statement"})
    # Body containers we descend through when collecting a statement sequence.
    BLOCK_NODE_TYPES: frozenset = frozenset(
        {
            "block",
            "statement_block",
            "compound_statement",
            "switch_body",
            "switch_block",
        }
    )
    # Single-level wrappers that hold the real statements (Go: block→statement_list).
    WRAPPER_NODE_TYPES: frozenset = frozenset({"statement_list"})
    # Map a loop node type to a short kind label.
    LOOP_KIND: dict = {
        "for_statement": "for",
        "while_statement": "while",
        "do_statement": "do",
        "for_in_statement": "for",
        "for_range_loop": "for",
        "foreach_statement": "foreach",
        "enhanced_for_statement": "for",
    }
    # Field name holding the function/method body.
    BODY_FIELD = "body"
    # Max characters kept for any single flow label (renderer truncates further).
    _FLOW_LABEL_CAP = 120

    def _slice(self, node, src: bytes) -> str:
        """Decode a node's source slice, collapse whitespace, cap length."""
        text = src[node.start_byte : node.end_byte].decode("utf-8", "replace")
        text = " ".join(text.split())
        if len(text) > self._FLOW_LABEL_CAP:
            text = text[: self._FLOW_LABEL_CAP - 1] + "…"
        return text

    @staticmethod
    def _strip_paren(text: str) -> str:
        text = text.strip()
        while text.startswith("(") and text.endswith(")"):
            text = text[1:-1].strip()
        return text

    def _looks_like_statement(self, node) -> bool:
        """Heuristic: is this named child a statement (vs. a keyword/expression)?"""
        t = node.type
        if (
            t in self.BLOCK_NODE_TYPES
            or t in self.WRAPPER_NODE_TYPES
            or t in self.IF_NODE_TYPES
            or t in self.ELIF_NODE_TYPES
            or t in self.LOOP_NODE_TYPES
            or t in self.SWITCH_NODE_TYPES
            or t in self.TRY_NODE_TYPES
            or t in self.RETURN_NODE_TYPES
            or t in self.BREAK_NODE_TYPES
            or t in self.CONTINUE_NODE_TYPES
            or t in self.THROW_NODE_TYPES
        ):
            return True
        return t.endswith(("_statement", "_declaration", "_definition"))

    def _statements(self, container):
        """Yield the meaningful statement nodes inside a body container."""
        if container is None:
            return
        for child in container.named_children:
            if child.type in self.WRAPPER_NODE_TYPES:
                yield from self._statements(child)
            elif self._looks_like_statement(child):
                yield child

    def _body_of(self, node):
        """Return the body/branch container of a control node, with fallbacks."""
        for fname in ("body", "consequence"):
            c = node.child_by_field_name(fname)
            if c is not None:
                return c
        for child in node.named_children:
            if (
                child.type in self.BLOCK_NODE_TYPES
                or child.type in self.WRAPPER_NODE_TYPES
                or child.type in self.IF_NODE_TYPES
            ):
                return child
        return None

    def _cond_text(self, node, src: bytes) -> str:
        for fname in ("condition", "value", "subject"):
            c = node.child_by_field_name(fname)
            if c is not None:
                # Unwrap a parenthesized / condition_clause wrapper.
                if c.type in ("parenthesized_expression", "condition_clause"):
                    inner = c.child_by_field_name("value")
                    if inner is not None:
                        return self._strip_paren(self._slice(inner, src))
                return self._strip_paren(self._slice(c, src))
        return ""

    def _build_flow(self, body_node, src: bytes) -> list:
        return self._flow_seq(body_node, src)

    def _flow_seq(self, container, src: bytes) -> list:
        """Convert a body container into a list of flow statements, merging
        consecutive simple statements into a single process block."""
        out: list = []
        pending: list[str] = []

        def flush():
            if pending:
                out.append({"t": "process", "lines": list(pending)})
                pending.clear()

        for stmt in self._statements(container):
            node = self._emit(stmt, src)
            if node is None:
                pending.append(self._slice(stmt, src))
            else:
                flush()
                if node.get("t") == "_inline":
                    out.extend(node["body"])
                else:
                    out.append(node)
        flush()
        return out

    def _emit(self, node, src: bytes):
        """Map a single statement node to a flow dict, or None if it is a plain
        simple statement that should be merged into a process block."""
        t = node.type
        if t in self.IF_NODE_TYPES:
            return self._flow_if(node, src)
        if t in self.LOOP_NODE_TYPES:
            return self._flow_loop(node, src)
        if t in self.SWITCH_NODE_TYPES:
            return self._flow_switch(node, src)
        if t in self.TRY_NODE_TYPES:
            return self._flow_try(node, src)
        if t in self.RETURN_NODE_TYPES:
            return {"t": "jump", "kind": "return", "label": self._slice(node, src)}
        if t in self.BREAK_NODE_TYPES:
            return {"t": "jump", "kind": "break", "label": self._slice(node, src)}
        if t in self.CONTINUE_NODE_TYPES:
            return {"t": "jump", "kind": "continue", "label": self._slice(node, src)}
        if t in self.THROW_NODE_TYPES:
            return {"t": "jump", "kind": "throw", "label": self._slice(node, src)}
        if t in self.BLOCK_NODE_TYPES or t in self.WRAPPER_NODE_TYPES:
            # A bare nested block: inline its statements.
            return {"t": "_inline", "body": self._flow_seq(node, src)}
        # Some grammars wrap a throw as an expression statement (PHP
        # throw_expression); surface it as a throw rather than a plain step.
        if t == "expression_statement":
            for ch in node.named_children:
                if ch.type in self.THROW_NODE_TYPES:
                    return {"t": "jump", "kind": "throw", "label": self._slice(node, src)}
        return None

    def _flow_branch(self, node, src: bytes) -> list:
        """Convert an `if`/`else` branch (a container or a single statement)
        into a statement list."""
        if node is None:
            return []
        if node.type in self.BLOCK_NODE_TYPES or node.type in self.WRAPPER_NODE_TYPES:
            return self._flow_seq(node, src)
        emitted = self._emit(node, src)
        if emitted is None:
            return [{"t": "process", "lines": [self._slice(node, src)]}]
        if emitted.get("t") == "_inline":
            return emitted["body"]
        return [emitted]

    def _flow_if(self, node, src: bytes) -> dict:
        then_body = node.child_by_field_name("consequence") or node.child_by_field_name("body")
        alts = [
            node.children[i]
            for i in range(node.child_count)
            if node.field_name_for_child(i) == "alternative"
        ]
        return {
            "t": "if",
            "cond": self._cond_text(node, src),
            "then": self._flow_branch(then_body, src),
            "else": self._fold_alts(alts, src),
        }

    def _fold_alts(self, alts, src: bytes) -> list:
        """Fold a chain of `alternative` nodes into a nested else structure.

        Handles three grammar shapes:
          * elif/else-if *clauses* with their own condition (Python, PHP)
          * `else` *clauses* wrapping a body (JS/TS, C++, Python)
          * bare `block` or bare `if_statement` as the alternative (Go, Java)
        """
        if not alts:
            return []
        a, rest = alts[0], alts[1:]
        t = a.type
        if t in self.ELIF_NODE_TYPES:
            return [
                {
                    "t": "if",
                    "cond": self._cond_text(a, src),
                    "then": self._flow_branch(self._body_of(a), src),
                    "else": self._fold_alts(rest, src),
                }
            ]
        if t in self.ELSE_NODE_TYPES:
            return self._flow_branch(self._body_of(a), src) + self._fold_alts(rest, src)
        # Bare alternative (Go/Java): a block (else) or an if_statement (else-if).
        return self._flow_branch(a, src) + self._fold_alts(rest, src)

    def _flow_loop(self, node, src: bytes) -> dict:
        body = self._body_of(node)
        end = body.start_byte if body is not None else node.end_byte
        header = src[node.start_byte : end].decode("utf-8", "replace")
        header = " ".join(header.split()).rstrip("{:( \t").strip()
        if len(header) > self._FLOW_LABEL_CAP:
            header = header[: self._FLOW_LABEL_CAP - 1] + "…"
        return {
            "t": "loop",
            "kind": self.LOOP_KIND.get(node.type, "loop"),
            "label": header,
            "body": self._flow_seq(body, src),
            "do": node.type in ("do_statement",),
        }

    def _flow_switch(self, node, src: bytes) -> dict:
        # Cases live inside a body container for most grammars, but Go attaches
        # expression_case/default_case directly to the switch node. Try the body
        # first, then fall back to the switch node's own children.
        cases: list = []
        body = self._body_of(node)
        for container in (c for c in (body, node) if c is not None):
            collected: list = []
            for child in container.named_children:
                if child.type in self.CASE_NODE_TYPES:
                    collected.append(
                        {
                            "label": self._case_label(child, src),
                            "body": self._case_body(child, src),
                        }
                    )
                elif self._looks_like_statement(child) and collected:
                    # Statements between labels (fall-through grammar) attach to
                    # the most recent case.
                    collected[-1]["body"].extend(self._flow_branch(child, src))
            if collected:
                cases = collected
                break
        return {"t": "switch", "label": self._cond_text(node, src), "cases": cases}

    def _case_label(self, node, src: bytes) -> str:
        """The `case X:` / `default:` header — text up to the first statement."""
        first = next(iter(self._statements(node)), None)
        end = first.start_byte if first is not None else node.end_byte
        text = src[node.start_byte : end].decode("utf-8", "replace")
        text = " ".join(text.split()).rstrip("{: \t").strip()
        if not text:
            text = self._slice(node, src)
        if len(text) > self._FLOW_LABEL_CAP:
            text = text[: self._FLOW_LABEL_CAP - 1] + "…"
        return text

    def _case_body(self, node, src: bytes) -> list:
        return self._flow_seq(node, src)

    def _flow_try(self, node, src: bytes) -> dict:
        body = node.child_by_field_name("body") or self._body_of(node)
        handlers: list = []
        final: list = []
        for child in node.named_children:
            if child.type in self.CATCH_NODE_TYPES:
                hbody = child.child_by_field_name("body") or self._body_of(child)
                handlers.append(
                    {
                        "label": self._case_label(child, src),
                        "body": self._flow_seq(hbody, src),
                    }
                )
            elif child.type in self.FINALLY_NODE_TYPES:
                fbody = child.child_by_field_name("body") or self._body_of(child)
                final = self._flow_seq(fbody, src)
        return {
            "t": "try",
            "body": self._flow_seq(body, src),
            "handlers": handlers,
            "final": final,
        }
