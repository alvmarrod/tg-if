.PHONY: install install-dev lint fmt format typecheck test check build run

install:
	uv sync

install-dev:
	uv sync --all-extras

lint:
	uv run ruff check src/ tests/

fmt: format
format:
	uv run ruff format src/ tests/

typecheck:
	uv run mypy src/ tests/

test:
	uv run pytest

check: lint typecheck test

precommit-install: install-dev
	pre-commit install

precommit:
	pre-commit run --all-files

build:
	docker build -t tg-if .

run:
	docker run --rm -p 8080:8080 --env-file .env tg-if
