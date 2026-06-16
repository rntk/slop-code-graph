"""C / C++ language parser."""

from __future__ import annotations

from .base import LanguageParser


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
