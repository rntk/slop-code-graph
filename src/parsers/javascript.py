"""JavaScript language parser (also base for TypeScript/TSX)."""

from __future__ import annotations

from .base import LanguageParser


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
