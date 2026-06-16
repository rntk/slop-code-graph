"""PHP language parser."""

from __future__ import annotations

from .base import LanguageParser


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
