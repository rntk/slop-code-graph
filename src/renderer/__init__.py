"""Renderer package.

Public API re-exports the main entry point used by graph.py and tests:
    from src.renderer import render
"""

from .render import render

__all__ = ["render"]
