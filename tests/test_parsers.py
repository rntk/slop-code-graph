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


# ---------------------------------------------------------------------------
# Control-flow ("block scheme" / flowchart) extraction
# ---------------------------------------------------------------------------

import pytest

from src.parsers import get_registry


def _parse_one(suffix, code, name="f"):
    """Parse `code`, returning the FunctionInfo named `name` (or None)."""
    parser = get_registry().get(suffix)
    if parser is None or not parser.available:
        pytest.skip(f"parser for {suffix} unavailable")
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
        f.write(code)
        f.flush()
        path = Path(f.name)
    try:
        funcs = parser.parse_file(path)
    finally:
        path.unlink()
    return next((fn for fn in funcs if fn.name == name), None)


def _kinds(flow):
    """Recursively collect the set of statement kinds in a flow tree."""
    seen = set()
    for s in flow or []:
        seen.add(s["t"])
        for key in ("then", "else", "body", "final"):
            seen |= _kinds(s.get(key))
        for key in ("handlers", "cases"):
            for sub in s.get(key, []):
                seen |= _kinds(sub.get("body"))
    return seen


def test_python_flow_structure():
    fn = _parse_one(".py", """
def f(x):
    a = 1
    for i in range(x):
        if i > 1:
            keep(i)
        elif i == 0:
            continue
        else:
            break
    while x:
        x -= 1
    try:
        risky()
    except ValueError:
        recover()
    finally:
        cleanup()
    return x
""")
    flow = fn.flow
    # First a process block grouping the simple assignment.
    assert flow[0]["t"] == "process"
    assert flow[0]["lines"] == ["a = 1"]

    loop = next(s for s in flow if s["t"] == "loop")
    assert loop["kind"] == "for"
    # The if inside the loop, with an elif folded into the else branch.
    iff = next(s for s in loop["body"] if s["t"] == "if")
    assert iff["cond"] == "i > 1"
    nested = iff["else"][0]
    assert nested["t"] == "if" and nested["cond"] == "i == 0"
    assert nested["then"][0] == {"t": "jump", "kind": "continue", "label": "continue"}
    assert nested["else"][0]["kind"] == "break"

    tryst = next(s for s in flow if s["t"] == "try")
    assert tryst["handlers"][0]["label"].startswith("except")
    assert tryst["final"]  # finally captured
    assert {"loop", "if", "try", "jump", "process"} <= _kinds(flow)


@pytest.mark.parametrize("suffix,code", [
    (".py", "def f(x):\n  for i in range(x):\n    if i>1: continue\n    else: break\n  while x: x-=1\n  match x:\n    case 1: return 1\n    case _: g()\n  try: g()\n  except E: h()\n  return x\n"),
    (".js", "function f(x){ for(let i=0;i<x;i++){ if(i>1){a()}else{break} } while(x){x--} switch(x){case 1: return 1; default: g()} try{g()}catch(e){h()} }"),
    (".ts", "function f(x:number){ if(x>0){a()}else if(x<0){b()}else{c()} for(let i=0;i<x;i++){w()} while(x){x--} switch(x){case 1: return 1; default: c()} return x }"),
    (".go", "package m\nfunc f(x int) int { for i:=0;i<x;i++ { if i>1 {continue} else {break} }; for x>0 {x--}; switch x {case 1: return 1; default: return 2} }"),
    (".java", "class C{int f(int x){ for(int i=0;i<x;i++){if(i>1)continue; else break;} while(x>0)x--; switch(x){case 1: a(); break; default: b();} try{g();}catch(Exception e){h();}finally{c();} throw new E(); }}"),
    (".cpp", "int f(int x){ for(int i=0;i<x;i++){if(i>1)continue; else break;} while(x>0)x--; switch(x){case 1: a(); break; default: b();} try{g();}catch(...){h();} throw 1; }"),
    (".php", "<?php function f($x){ for($i=0;$i<$x;$i++){if($i>1){continue;}else{break;}} while($x>0){$x--;} switch($x){case 1: return 1; default: g();} try{g();}catch(E $e){h();}finally{c();} throw new E(); }"),
])
def test_flow_covers_all_languages(suffix, code):
    fn = _parse_one(suffix, code)
    assert fn is not None, f"function not found for {suffix}"
    kinds = _kinds(fn.flow)
    # Every language sample exercises loops, conditionals and switches.
    assert "loop" in kinds, (suffix, kinds)
    assert "if" in kinds, (suffix, kinds)
    assert "switch" in kinds, (suffix, kinds)
    # break/continue/return all surface as jumps.
    assert "jump" in kinds, (suffix, kinds)


def test_flow_loop_back_edge_kinds():
    """do/while, for, while and foreach all map to a loop node with a kind."""
    fn = _parse_one(".js", "function f(){ do{a()}while(x); for(const k of arr){b()} }")
    kinds = {s.get("kind") for s in fn.flow if s["t"] == "loop"}
    assert "do" in kinds and "for" in kinds
