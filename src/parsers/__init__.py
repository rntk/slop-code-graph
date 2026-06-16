"""Language parsers using tree-sitter AST for function/call extraction.

This package is split into focused modules while preserving the original
public surface so that ``from src.parsers import ...`` continues to work
unchanged for both the CLI and tests.
"""

from __future__ import annotations

# Data model
from .models import FunctionInfo

# Base + mixin (rarely imported directly, but available)
from .base import LanguageParser
from .flow import FlowBuilder

# Language parsers
from .python import PythonParser
from .javascript import JavaScriptParser
from .typescript import TSXParser, TypeScriptParser
from .go import GoParser
from .java import JavaParser
from .cpp import CppParser
from .php import PHPParser

# Registry / entry points
from .registry import get_registry, get_parser_for_file, parse_files

__all__ = [
    # model
    "FunctionInfo",
    # base
    "LanguageParser",
    "FlowBuilder",
    # languages
    "PythonParser",
    "JavaScriptParser",
    "TypeScriptParser",
    "TSXParser",
    "GoParser",
    "JavaParser",
    "CppParser",
    "PHPParser",
    # registry
    "get_registry",
    "get_parser_for_file",
    "parse_files",
]
