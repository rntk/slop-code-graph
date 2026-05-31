"""Language parsers using tree-sitter AST for function/call extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FunctionInfo:
    """Represents a parsed function or method definition."""

    id: str  # unique: "file::qualified_name::start_line"
    name: str  # simple function name
    qualified_name: str  # "ClassName.method" or "method"
    file: str  # absolute path
    class_name: str | None
    start_line: int  # 1-indexed
    end_line: int  # 1-indexed
    source_code: str
    language: str
    calls: list[str] = field(default_factory=list)  # raw call names as seen in code
    # Structured control-flow of the body (for the "block scheme" / flowchart
    # view). A nested list of statement dicts — see LanguageParser._build_flow.
    flow: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Base parser
# ---------------------------------------------------------------------------


class LanguageParser:
    LANGUAGE_NAME = ""
    EXTENSIONS: list[str] = []
    CLASS_NODE_TYPES: frozenset = frozenset()
    FUNCTION_NODE_TYPES: frozenset = frozenset()
    CALL_NODE_TYPES: frozenset = frozenset()
    # Node types that carry a variable/field name hint for anonymous functions
    NAME_HINT_NODE_TYPES: frozenset = frozenset()

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

    def __init__(self):
        self._parser = None
        self._init_parser()

    def _get_language(self):
        raise NotImplementedError

    def _init_parser(self):
        try:
            from tree_sitter import Parser

            lang = self._get_language()
            if lang is None:
                return
            try:
                self._parser = Parser(lang)
            except TypeError:
                self._parser = Parser()
                self._parser.set_language(lang)  # type: ignore[attr-defined]
        except Exception as e:
            print(f"  [warn] Could not init {self.LANGUAGE_NAME} parser: {e}")

    @property
    def available(self) -> bool:
        return self._parser is not None

    def parse_file(self, file_path: Path) -> list[FunctionInfo]:
        if not self.available:
            return []
        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
            assert self._parser is not None
            tree = self._parser.parse(bytes(source, "utf-8"))
            return self._extract_functions(tree.root_node, source, str(file_path))
        except Exception as e:
            print(f"  [warn] Failed to parse {file_path}: {e}")
            return []

    # ------------------------------------------------------------------
    # Tree walker
    # ------------------------------------------------------------------

    def _extract_functions(self, root, source: str, file_path: str) -> list[FunctionInfo]:
        functions: list[FunctionInfo] = []
        source_lines = source.splitlines()
        src_bytes = source.encode("utf-8")

        def add_call(owner: FunctionInfo | None, node) -> None:
            """Attribute a call node to its owning (named) function, deduped."""
            if owner is None:
                return
            name = self._extract_call_name(node)
            if name and name not in owner.calls:
                owner.calls.append(name)

        def walk(
            node,
            class_ctx: str | None = None,
            name_hint: str | None = None,
            owner: FunctionInfo | None = None,
        ):
            t = node.type

            # --- Class nodes: update class context, recurse ---
            if t in self.CLASS_NODE_TYPES:
                cname = self._extract_class_name(node)
                for child in node.children:
                    walk(child, cname, None, owner)
                return

            # --- Name-hint carriers (variable_declarator, field_definition, pair) ---
            if t in self.NAME_HINT_NODE_TYPES:
                hint = self._extract_name_hint(node)
                for child in node.children:
                    walk(child, class_ctx, hint, owner)
                return

            # --- Function / method nodes ---
            if t in self.FUNCTION_NODE_TYPES:
                class_name, fname = self._resolve_function_identity(node, class_ctx, name_hint)
                # A named function becomes the owner for calls in its body. An
                # anonymous function (no resolvable name) gets no node of its
                # own, so its calls roll up into the enclosing named function —
                # otherwise callback/lambda bodies vanish from the flow.
                body_owner = owner
                if fname:
                    start_line = node.start_point[0]
                    end_line = node.end_point[0]
                    start_col = node.start_point[1]
                    src = "\n".join(source_lines[start_line : end_line + 1])
                    qualified = f"{class_name}.{fname}" if class_name else fname
                    func_id = f"{file_path}::{qualified}::{start_line}:{start_col}"

                    body_owner = FunctionInfo(
                        id=func_id,
                        name=fname,
                        qualified_name=qualified,
                        file=file_path,
                        class_name=class_name,
                        start_line=start_line + 1,
                        end_line=end_line + 1,
                        source_code=src,
                        language=self.LANGUAGE_NAME,
                    )
                    # Extract the structured control-flow of the body for the
                    # flowchart view. Best-effort: any failure leaves flow empty
                    # rather than breaking call-graph extraction.
                    try:
                        body_node = node.child_by_field_name(self.BODY_FIELD)
                        body_owner.flow = self._build_flow(body_node, src_bytes)
                    except Exception:
                        body_owner.flow = []
                    functions.append(body_owner)

                # Recurse into function body; reset class_ctx so inner functions
                # aren't incorrectly attributed to the outer class
                for child in node.children:
                    walk(child, None, None, body_owner)
                return

            # --- Call nodes: attribute to the current owner, then keep walking
            #     (arguments may contain further calls / nested functions) ---
            if t in self.CALL_NODE_TYPES:
                add_call(owner, node)

            # --- Default: recurse ---
            for child in node.children:
                walk(child, class_ctx, None, owner)

        walk(root)
        return functions

    # ------------------------------------------------------------------
    # Name extraction helpers (can be overridden per language)
    # ------------------------------------------------------------------

    def _extract_class_name(self, node) -> str:
        name_node = node.child_by_field_name("name")
        if name_node:
            return name_node.text.decode("utf-8")
        for child in node.children:
            if child.type in ("identifier", "type_identifier", "name"):
                return child.text.decode("utf-8")
        return "Unknown"

    def _extract_function_name(self, node) -> str | None:
        name_node = node.child_by_field_name("name")
        if name_node:
            return name_node.text.decode("utf-8")
        for child in node.children:
            if child.type in ("identifier", "name"):
                return child.text.decode("utf-8")
        return None

    def _extract_name_hint(self, node) -> str | None:
        """Extract the lhs name from variable_declarator / pair / field_definition."""
        # variable_declarator: name field
        name_node = node.child_by_field_name("name")
        if name_node:
            return name_node.text.decode("utf-8")
        # pair / field_definition: key / property field
        for field_name in ("key", "property"):
            kn = node.child_by_field_name(field_name)
            if kn:
                return kn.text.decode("utf-8")
        return None

    def _extract_receiver_class(self, node) -> str | None:
        """Go: extract class name from method receiver. Override in GoParser."""
        return None

    def _split_qualified_cpp_name(
        self, name: str | None, class_ctx: str | None
    ) -> tuple[str | None, str | None]:
        """C++: if name is 'ClassName::method', return ('ClassName', 'method')."""
        return None, name

    def _resolve_function_identity(
        self, node, class_ctx: str | None = None, name_hint: str | None = None
    ) -> tuple[str | None, str | None]:
        """Return (class_name, function_name) for a function node."""
        fname = self._extract_function_name(node) or name_hint
        recv_class = self._extract_receiver_class(node)
        class_name = recv_class or class_ctx

        # C++: qualified name like ClassName::method
        cpp_class, fname = self._split_qualified_cpp_name(fname, class_name)
        if cpp_class:
            class_name = cpp_class

        return class_name, fname

    def _extract_call_name(self, node) -> str | None:
        """Extract called function/method name from a call node."""
        # Try common field names for the callee
        for fname in ("function", "name"):
            func = node.child_by_field_name(fname)
            if func is not None:
                return self._name_from_expr(func)
        # Fallback: first named child that's not arguments
        for child in node.named_children:
            if child.type not in (
                "argument_list",
                "arguments",
                "call_suffix",
                "argument",
            ):
                result = self._name_from_expr(child)
                if result:
                    return result
        return None

    def _name_from_expr(self, node) -> str | None:
        """Resolve a callee expression node to a simple name string."""
        t = node.type
        if t in (
            "identifier",
            "property_identifier",
            "field_identifier",
            "type_identifier",
            "namespace_identifier",
            "name",
        ):
            return node.text.decode("utf-8")

        # Member access – return the last identifier (method name)
        if t in (
            "attribute",
            "member_expression",
            "selector_expression",
            "field_expression",
            "member_access_expression",
        ):
            for field_name in ("attribute", "property", "field"):
                sub = node.child_by_field_name(field_name)
                if sub:
                    return self._name_from_expr(sub)
            for child in reversed(node.named_children):
                result = self._name_from_expr(child)
                if result:
                    return result

        # Qualified / scoped identifiers (C++ ns::fn, Java Cls.m)
        if t in ("scoped_identifier", "qualified_identifier"):
            name_node = node.child_by_field_name("name")
            if name_node:
                return self._name_from_expr(name_node)
            for child in reversed(node.named_children):
                result = self._name_from_expr(child)
                if result:
                    return result

        # Recurse shallowly for other wrappers
        for child in node.named_children:
            result = self._name_from_expr(child)
            if result:
                return result
        return None

    # ==================================================================
    # Control-flow extraction (flowchart / "block scheme" view)
    #
    # Produces a nested list of statement dicts from a function body. Each
    # element is one of:
    #   {"t":"process", "lines":[str,...]}            run of simple statements
    #   {"t":"if", "cond":str, "then":[...], "else":[...]}
    #   {"t":"loop", "kind":str, "label":str, "body":[...], "do":bool}
    #   {"t":"switch", "label":str, "cases":[{"label":str,"body":[...]}]}
    #   {"t":"try", "body":[...], "handlers":[{"label","body"}], "final":[...]}
    #   {"t":"jump", "kind":"return|break|continue|throw", "label":str}
    # The renderer turns this tree into a flowchart graph in the browser.
    # ==================================================================

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


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------


class PythonParser(LanguageParser):
    LANGUAGE_NAME = "python"
    EXTENSIONS = [".py"]
    CLASS_NODE_TYPES = frozenset({"class_definition"})
    FUNCTION_NODE_TYPES = frozenset({"function_definition", "async_function_definition"})
    CALL_NODE_TYPES = frozenset({"call"})

    # Control flow
    ELIF_NODE_TYPES = frozenset({"elif_clause"})
    ELSE_NODE_TYPES = frozenset({"else_clause"})
    LOOP_NODE_TYPES = frozenset({"for_statement", "while_statement"})
    SWITCH_NODE_TYPES = frozenset({"match_statement"})
    CASE_NODE_TYPES = frozenset({"case_clause"})
    CATCH_NODE_TYPES = frozenset({"except_clause", "except_group_clause"})
    THROW_NODE_TYPES = frozenset({"raise_statement"})
    BLOCK_NODE_TYPES = frozenset({"block"})
    WRAPPER_NODE_TYPES = frozenset()

    def _get_language(self):
        import tree_sitter_python as m
        from tree_sitter import Language

        return Language(m.language())


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------


class JavaScriptParser(LanguageParser):
    LANGUAGE_NAME = "javascript"
    EXTENSIONS = [".js", ".mjs", ".cjs", ".jsx"]
    CLASS_NODE_TYPES = frozenset({"class_declaration", "class"})
    FUNCTION_NODE_TYPES = frozenset(
        {
            "function_declaration",
            "function",
            "function_expression",
            "arrow_function",
            "method_definition",
            "generator_function_declaration",
            "generator_function",
        }
    )
    CALL_NODE_TYPES = frozenset({"call_expression", "new_expression"})
    NAME_HINT_NODE_TYPES = frozenset(
        {
            "variable_declarator",
            "pair",
            "field_definition",
            "public_field_definition",
        }
    )

    # Control flow: C-family defaults + JS for-of/for-in loops.
    LOOP_NODE_TYPES = frozenset(
        {
            "for_statement",
            "while_statement",
            "do_statement",
            "for_in_statement",
        }
    )

    def _get_language(self):
        import tree_sitter_javascript as m
        from tree_sitter import Language

        return Language(m.language())

    def _extract_function_name(self, node) -> str | None:
        name_node = node.child_by_field_name("name")
        if name_node:
            return name_node.text.decode("utf-8")
        # method_definition may have property_identifier
        if node.type == "method_definition":
            for child in node.children:
                if child.type in (
                    "property_identifier",
                    "identifier",
                    "private_property_identifier",
                ):
                    return child.text.decode("utf-8")
        return None

    def _extract_call_name(self, node) -> str | None:
        if node.type == "new_expression":
            ctor = node.child_by_field_name("constructor")
            if ctor:
                return self._name_from_expr(ctor)
        return super()._extract_call_name(node)


# ---------------------------------------------------------------------------
# TypeScript  (extends JS, adds function signatures)
# ---------------------------------------------------------------------------


class TypeScriptParser(JavaScriptParser):
    LANGUAGE_NAME = "typescript"
    EXTENSIONS = [".ts"]
    FUNCTION_NODE_TYPES = JavaScriptParser.FUNCTION_NODE_TYPES | frozenset(
        {
            "function_signature",
            "method_signature",
            "abstract_method_signature",
        }
    )

    def _get_language(self):
        import tree_sitter_typescript as m
        from tree_sitter import Language

        return Language(m.language_typescript())


class TSXParser(TypeScriptParser):
    LANGUAGE_NAME = "tsx"
    EXTENSIONS = [".tsx"]

    def _get_language(self):
        import tree_sitter_typescript as m
        from tree_sitter import Language

        return Language(m.language_tsx())


# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------


class GoParser(LanguageParser):
    LANGUAGE_NAME = "go"
    EXTENSIONS = [".go"]
    CLASS_NODE_TYPES = frozenset()  # Go has no class keyword; use receiver
    FUNCTION_NODE_TYPES = frozenset(
        {
            "function_declaration",
            "method_declaration",
            "func_literal",
        }
    )
    CALL_NODE_TYPES = frozenset({"call_expression"})

    # Control flow: Go has no exceptions; else is a bare block/if (no else_clause).
    ELSE_NODE_TYPES = frozenset()
    LOOP_NODE_TYPES = frozenset({"for_statement"})
    SWITCH_NODE_TYPES = frozenset(
        {
            "expression_switch_statement",
            "type_switch_statement",
            "select_statement",
        }
    )
    CASE_NODE_TYPES = frozenset(
        {
            "expression_case",
            "default_case",
            "type_case",
            "communication_case",
        }
    )
    TRY_NODE_TYPES = frozenset()
    CATCH_NODE_TYPES = frozenset()
    FINALLY_NODE_TYPES = frozenset()
    THROW_NODE_TYPES = frozenset()
    BLOCK_NODE_TYPES = frozenset({"block"})
    WRAPPER_NODE_TYPES = frozenset({"statement_list"})

    def _get_language(self):
        import tree_sitter_go as m
        from tree_sitter import Language

        return Language(m.language())

    def _extract_function_name(self, node) -> str | None:
        name_node = node.child_by_field_name("name")
        if name_node:
            return name_node.text.decode("utf-8")
        return None

    def _extract_receiver_class(self, node) -> str | None:
        """Return the receiver type name for a Go method_declaration."""
        if node.type != "method_declaration":
            return None
        receiver = node.child_by_field_name("receiver")
        if receiver is None:
            return None
        for child in receiver.named_children:
            if child.type == "parameter_declaration":
                type_node = child.child_by_field_name("type")
                if type_node:
                    text = type_node.text.decode("utf-8").lstrip("*").strip()
                    return text if text else None
        return None


# ---------------------------------------------------------------------------
# Java
# ---------------------------------------------------------------------------


class JavaParser(LanguageParser):
    LANGUAGE_NAME = "java"
    EXTENSIONS = [".java"]
    CLASS_NODE_TYPES = frozenset(
        {
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
            "record_declaration",
            "annotation_type_declaration",
        }
    )
    FUNCTION_NODE_TYPES = frozenset(
        {
            "method_declaration",
            "constructor_declaration",
        }
    )
    CALL_NODE_TYPES = frozenset(
        {
            "method_invocation",
            "object_creation_expression",
            "explicit_generic_invocation",
        }
    )

    # Control flow: Java uses bare block/if for else (no else_clause) and
    # enhanced-for; switch is a switch_expression with statement groups.
    ELSE_NODE_TYPES = frozenset()
    LOOP_NODE_TYPES = frozenset(
        {
            "for_statement",
            "enhanced_for_statement",
            "while_statement",
            "do_statement",
        }
    )

    def _get_language(self):
        import tree_sitter_java as m
        from tree_sitter import Language

        return Language(m.language())

    def _extract_call_name(self, node) -> str | None:
        if node.type in ("method_invocation", "explicit_generic_invocation"):
            name_node = node.child_by_field_name("name")
            if name_node:
                return name_node.text.decode("utf-8")
        if node.type == "object_creation_expression":
            type_node = node.child_by_field_name("type")
            if type_node:
                return self._name_from_expr(type_node)
        return super()._extract_call_name(node)


# ---------------------------------------------------------------------------
# C / C++
# ---------------------------------------------------------------------------


class CppParser(LanguageParser):
    LANGUAGE_NAME = "cpp"
    EXTENSIONS = [".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx", ".c++"]
    CLASS_NODE_TYPES = frozenset({"class_specifier", "struct_specifier"})
    FUNCTION_NODE_TYPES = frozenset(
        {
            "function_definition",
            "lambda_expression",
        }
    )
    CALL_NODE_TYPES = frozenset({"call_expression"})

    # Control flow: C-family defaults + C++ range-for.
    LOOP_NODE_TYPES = frozenset(
        {
            "for_statement",
            "while_statement",
            "do_statement",
            "for_range_loop",
        }
    )

    def _get_language(self):
        import tree_sitter_cpp as m
        from tree_sitter import Language

        return Language(m.language())

    def _extract_class_name(self, node) -> str:
        name_node = node.child_by_field_name("name")
        if name_node:
            return name_node.text.decode("utf-8")
        return "Unknown"

    def _name_from_declarator(self, node) -> str | None:
        t = node.type
        if t in ("identifier", "field_identifier"):
            return node.text.decode("utf-8")
        if t == "function_declarator":
            inner = node.child_by_field_name("declarator")
            if inner:
                return self._name_from_declarator(inner)
        if t == "qualified_identifier":
            # Could be ClassName::method — return just the method part
            name_node = node.child_by_field_name("name")
            if name_node:
                return self._name_from_declarator(name_node)
            for child in reversed(node.named_children):
                result = self._name_from_declarator(child)
                if result:
                    return result
        if t in ("pointer_declarator", "reference_declarator"):
            for child in node.named_children:
                result = self._name_from_declarator(child)
                if result:
                    return result
        if t == "destructor_name":
            for child in node.children:
                if child.type == "identifier":
                    return f"~{child.text.decode('utf-8')}"
        if t == "operator_name":
            return node.text.decode("utf-8")
        return None

    def _extract_function_name(self, node) -> str | None:
        if node.type == "lambda_expression":
            return "<lambda>"
        decl = node.child_by_field_name("declarator")
        if decl is None:
            return None
        return self._name_from_declarator(decl)

    # For C++ out-of-class definitions (ClassName::method), also extract class
    def _cpp_class_from_declarator(self, node) -> str | None:
        """If declarator is ClassName::method, return ClassName."""
        decl = node.child_by_field_name("declarator")
        if decl is None:
            return None
        return self._class_from_decl(decl)

    def _class_from_decl(self, node) -> str | None:
        if node.type == "function_declarator":
            inner = node.child_by_field_name("declarator")
            if inner:
                return self._class_from_decl(inner)
        if node.type == "qualified_identifier":
            scope = node.child_by_field_name("scope")
            if scope:
                return scope.text.decode("utf-8")
        return None

    def _resolve_function_identity(self, node, class_ctx=None, name_hint=None):
        fname = self._extract_function_name(node) or name_hint
        cpp_class = self._cpp_class_from_declarator(node)
        class_name = cpp_class or class_ctx
        if fname and "::" in fname:
            parts = fname.rsplit("::", 1)
            class_name = parts[0]
            fname = parts[1]
        return class_name, fname


# ---------------------------------------------------------------------------
# PHP
# ---------------------------------------------------------------------------


class PHPParser(LanguageParser):
    LANGUAGE_NAME = "php"
    EXTENSIONS = [".php"]
    CLASS_NODE_TYPES = frozenset(
        {
            "class_declaration",
            "interface_declaration",
            "trait_declaration",
            "enum_declaration",
        }
    )
    FUNCTION_NODE_TYPES = frozenset(
        {
            "function_definition",
            "method_declaration",
            "arrow_function",
        }
    )
    CALL_NODE_TYPES = frozenset(
        {
            "function_call_expression",
            "member_call_expression",
            "scoped_call_expression",
            "object_creation_expression",
            "nullsafe_member_call_expression",
        }
    )

    # Control flow: PHP uses else_if_clause / else_clause and foreach.
    ELIF_NODE_TYPES = frozenset({"else_if_clause"})
    ELSE_NODE_TYPES = frozenset({"else_clause"})
    LOOP_NODE_TYPES = frozenset(
        {
            "for_statement",
            "while_statement",
            "do_statement",
            "foreach_statement",
        }
    )
    CASE_NODE_TYPES = frozenset({"case_statement", "default_statement"})
    THROW_NODE_TYPES = frozenset({"throw_statement", "throw_expression"})

    def _get_language(self):
        import tree_sitter_php as m
        from tree_sitter import Language

        return Language(m.language_php_only())

    def _extract_call_name(self, node) -> str | None:
        t = node.type
        if t == "function_call_expression":
            func = node.child_by_field_name("function")
            if func:
                return self._name_from_expr(func)
        if t in (
            "member_call_expression",
            "scoped_call_expression",
            "nullsafe_member_call_expression",
        ):
            name_node = node.child_by_field_name("name")
            if name_node:
                return name_node.text.decode("utf-8")
        if t == "object_creation_expression":
            # first named child is typically the class name
            for child in node.named_children:
                if child.type in (
                    "name",
                    "qualified_name",
                    "identifier",
                    "class_type_designator",
                    "named_type",
                ):
                    result = self._name_from_expr(child)
                    if result:
                        return result
        return super()._extract_call_name(node)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _build_registry() -> dict[str, LanguageParser]:
    registry: dict[str, LanguageParser] = {}
    parsers = [
        PythonParser,
        JavaScriptParser,
        TypeScriptParser,
        TSXParser,
        GoParser,
        JavaParser,
        CppParser,
        PHPParser,
    ]
    for cls in parsers:
        try:
            instance = cls()
            status = "ok" if instance.available else "unavailable"
            print(f"  Parser {cls.LANGUAGE_NAME:<12} [{status}]")
            if instance.available:
                for ext in cls.EXTENSIONS:
                    registry[ext] = instance
        except Exception as e:
            print(f"  Parser {cls.LANGUAGE_NAME:<12} [error: {e}]")
    return registry


_REGISTRY: dict[str, LanguageParser] | None = None


def get_registry() -> dict[str, LanguageParser]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY


def get_parser_for_file(file_path: Path) -> LanguageParser | None:
    return get_registry().get(file_path.suffix.lower())


def parse_files(file_paths: list[Path]) -> list[FunctionInfo]:
    registry = get_registry()
    all_functions: list[FunctionInfo] = []
    for fp in file_paths:
        parser = registry.get(fp.suffix.lower())
        if parser:
            fns = parser.parse_file(fp)
            all_functions.extend(fns)
    return all_functions
