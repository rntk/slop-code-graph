#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== Running dev checks ==="
echo

echo "--> Running linter (ruff check)..."
ruff check graph.py src/ tests/

echo "--> Running formatter check (ruff format --check)..."
ruff format --check graph.py src/ tests/

echo "--> Running type checker (mypy)..."
mypy graph.py src/ tests/

echo "--> Running tests (pytest)..."
pytest -v

echo
echo "=== All checks passed ==="
