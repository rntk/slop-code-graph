"""Canvas view pipeline: glue flow code, LLM topic-split, per-topic summaries."""

from .pipeline import build_canvas_data

__all__ = ["build_canvas_data"]
