"""Shared data models for parsers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FunctionInfo:
    """Represents a parsed function or method definition."""

    id: str  # unique: "file::qualified_name::start_line"
    name: str  # simple function name
    qualified_name: str  # "ClassName.method" or "method"
    file: str  # absolute path
    class_name: str | None
    start_line: int  # 1-indexed
    end_line: int  # 1-indexed
    source_code: str
    language: str
    calls: list[str] = field(default_factory=list)  # raw call names as seen in code
    # Binding names introduced by this function's own parameter list (including
    # destructured/renamed bindings). A call to one of these names is a *local*
    # reference (e.g. an injected callback), not a module-level function, so it
    # must not be resolved to same-named definitions elsewhere. See base.py.
    param_names: set[str] = field(default_factory=set)
    # Structured control-flow of the body (for the "block scheme" / flowchart
    # view). A nested list of statement dicts — see LanguageParser._build_flow.
    flow: list = field(default_factory=list)
