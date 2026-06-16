"""Go language parser."""

from __future__ import annotations

from .base import LanguageParser


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
