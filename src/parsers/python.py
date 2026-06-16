"""Python language parser."""

from __future__ import annotations

from .base import LanguageParser


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
