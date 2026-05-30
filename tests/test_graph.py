"""Tests for graph.py CLI and file collection."""

import tempfile
from pathlib import Path

from graph import collect_files, SUPPORTED_EXTENSIONS


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
        assert False, "Expected SystemExit"
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
