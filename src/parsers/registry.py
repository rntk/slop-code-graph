"""Parser registry and high-level parse entry points."""

from __future__ import annotations

from pathlib import Path

from .base import LanguageParser
from .cpp import CppParser
from .go import GoParser
from .java import JavaParser
from .javascript import JavaScriptParser
from .php import PHPParser
from .python import PythonParser
from .typescript import TSXParser, TypeScriptParser

from .models import FunctionInfo  # re-export for convenience in this module


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
