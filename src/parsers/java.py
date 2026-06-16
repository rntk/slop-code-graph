"""Java language parser."""

from __future__ import annotations

from .base import LanguageParser


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
