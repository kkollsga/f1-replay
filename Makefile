.PHONY: install test test-cov lint format check clean run docs

install:
	pip install -e ".[dev,all]"

test:
	pytest tests/ -v --tb=short

test-cov:
	pytest tests/ -v --cov=f1_replay --cov-report=term-missing

lint:
	black --check --diff f1_replay/ tests/
	isort --check --diff f1_replay/ tests/
	flake8 f1_replay/ tests/

format:
	black f1_replay/ tests/
	isort f1_replay/ tests/

check: lint test

docs:
	sphinx-build -b html docs docs/_build

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .coverage htmlcov/ docs/_build/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

run:
	python -m f1_replay.api.cli server
