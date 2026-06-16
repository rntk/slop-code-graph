"""Base language parser with tree-sitter AST walking and name extraction."""

from __future__ import annotations

from pathlib import Path

from .flow import FlowBuilder
from .models import FunctionInfo


class LanguageParser(FlowBuilder):
    """Base parser for a language using tree-sitter.

    Subclasses set the node type sets and implement _get_language().
    The FlowBuilder mixin supplies the _build_flow* control-flow logic.
    """

    LANGUAGE_NAME = ""
    EXTENSIONS: list[str] = []
    CLASS_NODE_TYPES: frozenset = frozenset()
    FUNCTION_NODE_TYPES: frozenset = frozenset()
    CALL_NODE_TYPES: frozenset = frozenset()
    # Node types that carry a variable/field name hint for anonymous functions
    NAME_HINT_NODE_TYPES: frozenset = frozenset()

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
