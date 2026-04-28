.PHONY: setup clean dev test lint typecheck format build ci

setup:
	asdf install
	pip install -e ".[dev]"

clean:
	rm -rf build/ dist/ *.egg-info .mypy_cache .ruff_cache .pytest_cache htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} +

dev:
	@echo "No dev server — tdf2mzml is a CLI tool. Use: tdf2mzml --help"

test:
	python -m pytest -m "not slow" --cov=tdf2mzml --cov-report=term-missing

test-all:
	python -m pytest --cov=tdf2mzml --cov-report=term-missing

lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

typecheck:
	mypy src/tdf2mzml/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

build:
	docker build -t mfreitas/tdf2mzml:dev -f Dockerfile .
	docker build -t mfreitas/tdf2mzml:dev-noentry -f Dockerfile.noentry .

ci: lint typecheck test
