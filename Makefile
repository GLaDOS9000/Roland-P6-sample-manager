setup:
	uv venv -p 3.13

install:
	uv sync

start:
	uv run pyp6

start-legacy:
	uv run PyP6-Roland-P6-Sample-Manager_3_0_0.py

test:
	uv run pytest
