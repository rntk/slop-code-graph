.PHONY: help install install-dev test lint format typecheck check fix docker-build docker-run

PYTHON := python
PIP := pip

help:
	@echo "Available targets:"
	@echo "  install       Install production dependencies"
	@echo "  install-dev   Install development dependencies"
	@echo "  test          Run pytest suite"
	@echo "  lint          Run ruff linter"
	@echo "  format        Run ruff formatter (check mode)"
	@echo "  fix           Run ruff linter and formatter (apply fixes)"
	@echo "  typecheck     Run mypy type checker"
	@echo "  check         Run lint + format + typecheck + test"
	@echo "  docker-build  Build production Docker image"
	@echo "  docker-run    Run production Docker container (usage: make docker-run ARGS=\"...\")"
	@echo "  docker-dev    Build and run dev Docker container"

install:
	$(PIP) install -r requirements.txt

install-dev:
	$(PIP) install -r requirements-dev.txt

test:
	pytest -v

lint:
	ruff check graph.py src/ traverse/ llm/ tests/

format:
	ruff format --check graph.py src/ traverse/ llm/ tests/

fix:
	ruff check --fix graph.py src/ tests/
	ruff format graph.py src/ tests/

typecheck:
	mypy graph.py src/ tests/

check: lint format typecheck test

docker-build:
	docker build -t callgraph .

docker-run:
	docker run --rm -v $(PWD):/code callgraph $(ARGS)

docker-dev:
	docker build -f Dockerfile.dev -t callgraph-dev .
	docker run --rm -it -v $(PWD):/app callgraph-dev bash

docker-traverse-build:
	docker build -f Dockerfile.traverse -t traverse .

docker-traverse-run:
	docker run --rm -it -p 8765:8765 -v $(PWD):/workspace -w /workspace traverse

