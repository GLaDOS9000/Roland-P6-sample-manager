setup:
	uv venv -p 3.13

install:
	uv sync --extra dev
	uv run pre-commit install

start:
	uv run pyp6

start-legacy:
	uv run PyP6-Roland-P6-Sample-Manager_3_0_0.py

test:
	uv run --extra dev pytest

lint:
	uv run --extra dev ruff check src tests

format:
	uv run --extra dev ruff format src tests

fix:
	uv run --extra dev ruff check --fix src tests && uv run --extra dev ruff format src tests
