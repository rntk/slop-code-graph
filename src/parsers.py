"""Language parsers using tree-sitter AST for function/call extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class FunctionInfo:
    """Represents a parsed function or method definition."""
    id: str               # unique: "file::qualified_name::start_line"
    name: str             # simple function name
    qualified_name: str   # "ClassName.method" or "method"
    file: str             # absolute path
    class_name: Optional[str]
    start_line: int       # 1-indexed
    end_line: int         # 1-indexed
    source_code: str
    language: str
    calls: list = field(default_factory=list)  # raw call names as seen in code


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

    def __init__(self):
        self._parser = None
        self._init_parser()

    def _get_language(self):
        raise NotImplementedError

    def _init_parser(self):
        try:
            from tree_sitter import Language, Parser
            lang = self._get_language()
            if lang is None:
                return
            try:
                self._parser = Parser(lang)
            except TypeError:
                self._parser = Parser()
                self._parser.set_language(lang)
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
            tree = self._parser.parse(bytes(source, "utf-8"))
            return self._extract_functions(tree.root_node, source, str(file_path))
        except Exception as e:
            print(f"  [warn] Failed to parse {file_path}: {e}")
            return []

    # ------------------------------------------------------------------
    # Tree walker
    # ------------------------------------------------------------------

    def _extract_functions(
        self, root, source: str, file_path: str
    ) -> list[FunctionInfo]:
        functions: list[FunctionInfo] = []
        source_lines = source.splitlines()

        def get_calls(func_node) -> list[str]:
            """Collect call names reachable from func_node, not crossing nested boundaries."""
            calls: list[str] = []
            seen: set[str] = set()

            def visit(node):
                if node.type in self.CALL_NODE_TYPES:
                    name = self._extract_call_name(node)
                    if name and name not in seen:
                        calls.append(name)
                        seen.add(name)
                for child in node.children:
                    if (
                        child.type not in self.FUNCTION_NODE_TYPES
                        and child.type not in self.CLASS_NODE_TYPES
                    ):
                        visit(child)

            for child in func_node.children:
                visit(child)
            return calls

        def walk(node, class_ctx: Optional[str] = None, name_hint: Optional[str] = None):
            t = node.type

            # --- Class nodes: update class context, recurse ---
            if t in self.CLASS_NODE_TYPES:
                cname = self._extract_class_name(node)
                for child in node.children:
                    walk(child, cname, None)
                return

            # --- Name-hint carriers (variable_declarator, field_definition, pair) ---
            if t in self.NAME_HINT_NODE_TYPES:
                hint = self._extract_name_hint(node)
                for child in node.children:
                    walk(child, class_ctx, hint)
                return

            # --- Function / method nodes ---
            if t in self.FUNCTION_NODE_TYPES:
                # Prefer explicit name over parent hint
                fname = self._extract_function_name(node) or name_hint
                # Go: derive class from receiver
                recv_class = self._extract_receiver_class(node)
                class_name = recv_class or class_ctx

                # C++: qualified name like ClassName::method
                cpp_class, fname = self._split_qualified_cpp_name(fname, class_name)
                if cpp_class:
                    class_name = cpp_class

                if fname:
                    start = node.start_point[0]
                    end = node.end_point[0]
                    src = "\n".join(source_lines[start : end + 1])
                    qualified = f"{class_name}.{fname}" if class_name else fname
                    func_id = f"{file_path}::{qualified}::{start}"

                    functions.append(
                        FunctionInfo(
                            id=func_id,
                            name=fname,
                            qualified_name=qualified,
                            file=file_path,
                            class_name=class_name,
                            start_line=start + 1,
                            end_line=end + 1,
                            source_code=src,
                            language=self.LANGUAGE_NAME,
                            calls=get_calls(node),
                        )
                    )

                # Recurse into function body; reset class_ctx so inner functions
                # aren't incorrectly attributed to the outer class
                for child in node.children:
                    walk(child, None, None)
                return

            # --- Default: recurse ---
            for child in node.children:
                walk(child, class_ctx, None)

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

    def _extract_function_name(self, node) -> Optional[str]:
        name_node = node.child_by_field_name("name")
        if name_node:
            return name_node.text.decode("utf-8")
        for child in node.children:
            if child.type in ("identifier", "name"):
                return child.text.decode("utf-8")
        return None

    def _extract_name_hint(self, node) -> Optional[str]:
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

    def _extract_receiver_class(self, node) -> Optional[str]:
        """Go: extract class name from method receiver. Override in GoParser."""
        return None

    def _split_qualified_cpp_name(
        self, name: Optional[str], class_ctx: Optional[str]
    ) -> tuple[Optional[str], Optional[str]]:
        """C++: if name is 'ClassName::method', return ('ClassName', 'method')."""
        return None, name

    def _extract_call_name(self, node) -> Optional[str]:
        """Extract called function/method name from a call node."""
        # Try common field names for the callee
        for fname in ("function", "name"):
            func = node.child_by_field_name(fname)
            if func is not None:
                return self._name_from_expr(func)
        # Fallback: first named child that's not arguments
        for child in node.named_children:
            if child.type not in (
                "argument_list", "arguments", "call_suffix", "argument",
            ):
                result = self._name_from_expr(child)
                if result:
                    return result
        return None

    def _name_from_expr(self, node) -> Optional[str]:
        """Resolve a callee expression node to a simple name string."""
        t = node.type
        if t in (
            "identifier", "property_identifier", "field_identifier",
            "type_identifier", "namespace_identifier", "name",
        ):
            return node.text.decode("utf-8")

        # Member access – return the last identifier (method name)
        if t in (
            "attribute", "member_expression", "selector_expression",
            "field_expression", "member_access_expression",
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


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------

class PythonParser(LanguageParser):
    LANGUAGE_NAME = "python"
    EXTENSIONS = [".py"]
    CLASS_NODE_TYPES = frozenset({"class_definition"})
    FUNCTION_NODE_TYPES = frozenset({"function_definition"})
    CALL_NODE_TYPES = frozenset({"call"})

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
    FUNCTION_NODE_TYPES = frozenset({
        "function_declaration", "function", "arrow_function",
        "method_definition", "generator_function_declaration",
        "generator_function",
    })
    CALL_NODE_TYPES = frozenset({"call_expression", "new_expression"})
    NAME_HINT_NODE_TYPES = frozenset({
        "variable_declarator", "pair", "field_definition",
        "public_field_definition",
    })

    def _get_language(self):
        import tree_sitter_javascript as m
        from tree_sitter import Language
        return Language(m.language())

    def _extract_function_name(self, node) -> Optional[str]:
        name_node = node.child_by_field_name("name")
        if name_node:
            return name_node.text.decode("utf-8")
        # method_definition may have property_identifier
        if node.type == "method_definition":
            for child in node.children:
                if child.type in ("property_identifier", "identifier",
                                  "private_property_identifier"):
                    return child.text.decode("utf-8")
        return None

    def _extract_call_name(self, node) -> Optional[str]:
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
    FUNCTION_NODE_TYPES = JavaScriptParser.FUNCTION_NODE_TYPES | frozenset({
        "function_signature", "method_signature",
        "abstract_method_signature",
    })

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
    FUNCTION_NODE_TYPES = frozenset({
        "function_declaration", "method_declaration", "func_literal",
    })
    CALL_NODE_TYPES = frozenset({"call_expression"})

    def _get_language(self):
        import tree_sitter_go as m
        from tree_sitter import Language
        return Language(m.language())

    def _extract_function_name(self, node) -> Optional[str]:
        name_node = node.child_by_field_name("name")
        if name_node:
            return name_node.text.decode("utf-8")
        return None

    def _extract_receiver_class(self, node) -> Optional[str]:
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
    CLASS_NODE_TYPES = frozenset({
        "class_declaration", "interface_declaration",
        "enum_declaration", "record_declaration",
        "annotation_type_declaration",
    })
    FUNCTION_NODE_TYPES = frozenset({
        "method_declaration", "constructor_declaration",
    })
    CALL_NODE_TYPES = frozenset({
        "method_invocation", "object_creation_expression",
        "explicit_generic_invocation",
    })

    def _get_language(self):
        import tree_sitter_java as m
        from tree_sitter import Language
        return Language(m.language())

    def _extract_call_name(self, node) -> Optional[str]:
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
    FUNCTION_NODE_TYPES = frozenset({
        "function_definition", "lambda_expression",
    })
    CALL_NODE_TYPES = frozenset({"call_expression"})

    def _get_language(self):
        import tree_sitter_cpp as m
        from tree_sitter import Language
        return Language(m.language())

    def _extract_class_name(self, node) -> str:
        name_node = node.child_by_field_name("name")
        if name_node:
            return name_node.text.decode("utf-8")
        return "Unknown"

    def _name_from_declarator(self, node) -> Optional[str]:
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

    def _extract_function_name(self, node) -> Optional[str]:
        if node.type == "lambda_expression":
            return "<lambda>"
        decl = node.child_by_field_name("declarator")
        if decl is None:
            return None
        return self._name_from_declarator(decl)

    # For C++ out-of-class definitions (ClassName::method), also extract class
    def _cpp_class_from_declarator(self, node) -> Optional[str]:
        """If declarator is ClassName::method, return ClassName."""
        decl = node.child_by_field_name("declarator")
        if decl is None:
            return None
        return self._class_from_decl(decl)

    def _class_from_decl(self, node) -> Optional[str]:
        if node.type == "function_declarator":
            inner = node.child_by_field_name("declarator")
            if inner:
                return self._class_from_decl(inner)
        if node.type == "qualified_identifier":
            scope = node.child_by_field_name("scope")
            if scope:
                return scope.text.decode("utf-8")
        return None

    def _extract_functions(self, root, source, file_path):
        # Use a modified walk that also extracts C++ class from out-of-class definitions
        functions: list[FunctionInfo] = []
        source_lines = source.splitlines()

        def get_calls(func_node):
            calls: list[str] = []
            seen: set[str] = set()

            def visit(node):
                if node.type in self.CALL_NODE_TYPES:
                    n = self._extract_call_name(node)
                    if n and n not in seen:
                        calls.append(n)
                        seen.add(n)
                for child in node.children:
                    if child.type not in self.FUNCTION_NODE_TYPES and child.type not in self.CLASS_NODE_TYPES:
                        visit(child)

            for child in func_node.children:
                visit(child)
            return calls

        def walk(node, class_ctx=None, name_hint=None):
            t = node.type
            if t in self.CLASS_NODE_TYPES:
                cname = self._extract_class_name(node)
                for child in node.children:
                    walk(child, cname, None)
                return
            if t in self.FUNCTION_NODE_TYPES:
                fname = self._extract_function_name(node)
                # For out-of-class definitions, extract class from qualified declarator
                cpp_class = self._cpp_class_from_declarator(node)
                class_name = cpp_class or class_ctx
                if fname and "::" in fname:
                    parts = fname.rsplit("::", 1)
                    class_name = parts[0]
                    fname = parts[1]
                if fname:
                    start = node.start_point[0]
                    end = node.end_point[0]
                    src = "\n".join(source_lines[start : end + 1])
                    qualified = f"{class_name}.{fname}" if class_name else fname
                    func_id = f"{file_path}::{qualified}::{start}"
                    functions.append(
                        FunctionInfo(
                            id=func_id,
                            name=fname,
                            qualified_name=qualified,
                            file=file_path,
                            class_name=class_name,
                            start_line=start + 1,
                            end_line=end + 1,
                            source_code="\n".join(source_lines[start : end + 1]),
                            language=self.LANGUAGE_NAME,
                            calls=get_calls(node),
                        )
                    )
                for child in node.children:
                    walk(child, None, None)
                return
            for child in node.children:
                walk(child, class_ctx, None)

        walk(root)
        return functions


# ---------------------------------------------------------------------------
# PHP
# ---------------------------------------------------------------------------

class PHPParser(LanguageParser):
    LANGUAGE_NAME = "php"
    EXTENSIONS = [".php"]
    CLASS_NODE_TYPES = frozenset({
        "class_declaration", "interface_declaration",
        "trait_declaration", "enum_declaration",
    })
    FUNCTION_NODE_TYPES = frozenset({
        "function_definition", "method_declaration", "arrow_function",
    })
    CALL_NODE_TYPES = frozenset({
        "function_call_expression", "member_call_expression",
        "scoped_call_expression", "object_creation_expression",
        "nullsafe_member_call_expression",
    })

    def _get_language(self):
        import tree_sitter_php as m
        from tree_sitter import Language
        return Language(m.language_php_only())

    def _extract_call_name(self, node) -> Optional[str]:
        t = node.type
        if t == "function_call_expression":
            func = node.child_by_field_name("function")
            if func:
                return self._name_from_expr(func)
        if t in ("member_call_expression", "scoped_call_expression",
                 "nullsafe_member_call_expression"):
            name_node = node.child_by_field_name("name")
            if name_node:
                return name_node.text.decode("utf-8")
        if t == "object_creation_expression":
            # first named child is typically the class name
            for child in node.named_children:
                if child.type in ("name", "qualified_name", "identifier",
                                  "class_type_designator", "named_type"):
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
        PythonParser, JavaScriptParser, TypeScriptParser, TSXParser,
        GoParser, JavaParser, CppParser, PHPParser,
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


_REGISTRY: Optional[dict[str, LanguageParser]] = None


def get_registry() -> dict[str, LanguageParser]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY


def get_parser_for_file(file_path: Path) -> Optional[LanguageParser]:
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
