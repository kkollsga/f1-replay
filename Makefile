.PHONY: install test test-cov lint format clean run

install:
	pip install -e ".[dev,all]"

test:
	pytest tests/ -v --tb=short

test-cov:
	pytest tests/ -v --cov=f1_replay --cov-report=term-missing

lint:
	flake8 f1_replay/ tests/ --max-line-length=100 --ignore=E501,W503
	isort --check-only f1_replay/ tests/

format:
	black f1_replay/ tests/
	isort f1_replay/ tests/

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .coverage htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

run:
	python -m f1_replay.api.cli server
