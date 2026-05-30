"""Tests for language parsers."""

import tempfile
from pathlib import Path

from src.parsers import (
    PythonParser,
    JavaScriptParser,
    FunctionInfo,
    get_parser_for_file,
)


def test_python_parser_extracts_functions():
    parser = PythonParser()
    if not parser.available:
        return

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("""
def foo():
    bar()

class MyClass:
    def method(self):
        baz()
""")
        f.flush()
        path = Path(f.name)

    funcs = parser.parse_file(path)
    path.unlink()

    names = {fn.name for fn in funcs}
    assert "foo" in names
    assert "method" in names

    foo = next(fn for fn in funcs if fn.name == "foo")
    assert foo.calls == ["bar"]
    assert foo.class_name is None

    method = next(fn for fn in funcs if fn.name == "method")
    assert method.calls == ["baz"]
    assert method.class_name == "MyClass"
    assert method.qualified_name == "MyClass.method"


def test_python_parser_async_function():
    parser = PythonParser()
    if not parser.available:
        return

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("""
async def fetch():
    await get_data()
""")
        f.flush()
        path = Path(f.name)

    funcs = parser.parse_file(path)
    path.unlink()

    names = {fn.name for fn in funcs}
    assert "fetch" in names

    fetch = next(fn for fn in funcs if fn.name == "fetch")
    assert fetch.calls == ["get_data"]


def test_function_info_calls_typed():
    """FunctionInfo.calls should be a list of strings."""
    fn = FunctionInfo(
        id="test",
        name="foo",
        qualified_name="foo",
        file="/test.py",
        class_name=None,
        start_line=1,
        end_line=1,
        source_code="def foo(): pass",
        language="python",
        calls=["bar", "baz"],
    )
    assert fn.calls == ["bar", "baz"]


def test_unique_id_includes_column():
    """Overloaded functions on the same line must get unique IDs."""
    parser = PythonParser()
    if not parser.available:
        return

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("def foo(): pass\ndef bar(): pass\n")
        f.flush()
        path = Path(f.name)

    funcs = parser.parse_file(path)
    path.unlink()

    ids = [fn.id for fn in funcs]
    assert len(ids) == len(set(ids)), f"Duplicate IDs found: {ids}"


def test_javascript_parser_name_hint():
    parser = JavaScriptParser()
    if not parser.available:
        return

    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
        f.write("""
const myFunc = function() {
    helper();
};
""")
        f.flush()
        path = Path(f.name)

    funcs = parser.parse_file(path)
    path.unlink()

    names = {fn.name for fn in funcs}
    assert "myFunc" in names


def test_get_parser_for_file():
    assert get_parser_for_file(Path("test.py")) is not None
    assert get_parser_for_file(Path("test.js")) is not None
    assert get_parser_for_file(Path("test.txt")) is None
