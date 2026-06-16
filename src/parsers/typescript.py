"""TypeScript and TSX language parsers (extend JavaScriptParser)."""

from __future__ import annotations

from .javascript import JavaScriptParser


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
