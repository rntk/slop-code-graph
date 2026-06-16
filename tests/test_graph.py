"""Tests for graph.py CLI and file collection."""

import tempfile
from pathlib import Path

from graph import collect_files


def test_collect_files_single_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("def foo(): pass\n")
        f.flush()
        path = Path(f.name)

    result = collect_files(path)
    assert result == [path]
    path.unlink()


def test_collect_files_unsupported_extension():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.flush()
        path = Path(f.name)

    import sys
    from io import StringIO

    old_stderr = sys.stderr
    sys.stderr = StringIO()
    try:
        collect_files(path)
        raise AssertionError("Expected SystemExit")
    except SystemExit as e:
        assert "unsupported file type" in str(e)
    finally:
        sys.stderr = old_stderr
        path.unlink()


def test_collect_files_ignores_directories():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "src").mkdir()
        (root / "src" / "main.py").write_text("def main(): pass\n")
        (root / "__pycache__").mkdir()
        (root / "__pycache__" / "cached.cpython-312.pyc").write_text("")
        (root / "node_modules").mkdir()
        (root / "node_modules" / "lib.js").write_text("function foo() {}\n")

        result = collect_files(root)
        files = [p.name for p in result]
        assert "main.py" in files
        assert "cached.cpython-312.pyc" not in files
        assert "lib.js" not in files


def test_collect_files_symlink_not_followed():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "real.py").write_text("def foo(): pass\n")
        (root / "link.py").symlink_to(root / "real.py")

        result = collect_files(root)
        files = [p.name for p in result]
        assert files.count("real.py") == 1
        assert "link.py" not in files


class MockLLM:
    def __init__(self, content="Mocked LLM summary response"):
        self.content = content
        self.call_count = 0
        self.last_user_prompt = None

    def complete(self, user_prompt, system_prompt, temperature):
        self.call_count += 1
        self.last_user_prompt = user_prompt
        from types import SimpleNamespace

        return SimpleNamespace(content=self.content)


def test_build_file_summaries_caching():
    import json

    from graph import _build_file_summaries
    from src.graph_builder import build_graph
    from src.parsers import FunctionInfo

    # Create dummy functions that belong to one file
    f1 = FunctionInfo(
        id="f1",
        name="foo",
        qualified_name="foo",
        file="/test.py",
        class_name=None,
        start_line=1,
        end_line=5,
        source_code="def foo():\n    return 42",
        language="python",
        calls=[],
        flow=[],
    )
    graph = build_graph([f1])
    # Ensure relative_file is populated
    for node in graph.nodes:
        node.relative_file = "test.py"

    mock_llm = MockLLM("Test summary of the file.")

    with tempfile.TemporaryDirectory() as tmp_dir:
        cache_path = Path(tmp_dir)

        # 1. First run: cache is empty, should call LLM
        summaries1 = _build_file_summaries(graph, mock_llm, cache_dir=cache_path)
        assert summaries1 == {"test.py": "Test summary of the file."}
        assert mock_llm.call_count == 1

        # Check that cache file exists and contains the key
        cache_file = cache_path / "graph_llm_cache.json"
        assert cache_file.exists()
        with open(cache_file, encoding="utf-8") as f:
            cache_data = json.load(f)
        assert len(cache_data) == 1
        cached_key = list(cache_data.keys())[0]
        assert cache_data[cached_key] == "Test summary of the file."

        # 2. Second run: cache is populated, should NOT call LLM
        mock_llm_cached = MockLLM("Different summary (should not be returned)")
        summaries2 = _build_file_summaries(graph, mock_llm_cached, cache_dir=cache_path)
        assert summaries2 == {"test.py": "Test summary of the file."}
        assert mock_llm_cached.call_count == 0

        # 3. Third run: with different source code, prompt changes, should call LLM
        f1_new = FunctionInfo(
            id="f1",
            name="foo",
            qualified_name="foo",
            file="/test.py",
            class_name=None,
            start_line=1,
            end_line=5,
            source_code="def foo():\n    return 999",  # changed
            language="python",
            calls=[],
            flow=[],
        )
        graph_new = build_graph([f1_new])
        for node in graph_new.nodes:
            node.relative_file = "test.py"

        mock_llm_changed = MockLLM("Updated summary.")
        summaries3 = _build_file_summaries(graph_new, mock_llm_changed, cache_dir=cache_path)
        assert summaries3 == {"test.py": "Updated summary."}
        assert mock_llm_changed.call_count == 1
