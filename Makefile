.PHONY: help test lint format typecheck integration infra all clean

# Default target
help:
	@echo "Popcorn Sales Manager - Build & Test Commands"
	@echo ""
	@echo "Testing:"
	@echo "  make test              - Run Python unit tests (pytest)"
	@echo "  make test-frontend     - Run TypeScript unit tests (vitest)"
	@echo "  make test-e2e          - Run E2E tests (playwright)"
	@echo "  make test-integration  - Run integration tests"
	@echo "  make test-all          - Run all tests (unit + integration + e2e)"
	@echo ""
	@echo "Linting & Type Checking:"
	@echo "  make lint              - Run all linters (Python + TypeScript)"
	@echo "  make lint-python       - Run Python linters (ruff + mypy)"
	@echo "  make lint-frontend     - Run TypeScript linters (eslint + tsc)"
	@echo "  make typecheck         - Run type checkers (mypy + tsc)"
	@echo ""
	@echo "Formatting:"
	@echo "  make format            - Format all code (Python + TypeScript)"
	@echo "  make format-python     - Format Python code (isort + ruff)"
	@echo "  make format-frontend   - Format TypeScript code (prettier)"
	@echo ""
	@echo "Infrastructure Scanning:"
	@echo "  make lint-infra        - Run infrastructure checks (tflint + kics)"
	@echo "  make tflint            - Run tflint on OpenTofu code"
	@echo "  make kics              - Run KICS security scan"
	@echo ""
	@echo "Comprehensive:"
	@echo "  make all               - Run everything (format + lint + typecheck + test)"
	@echo "  make ci                - Run CI pipeline (lint + typecheck + test)"
	@echo "  make clean             - Clean generated files"

# Python unit tests
test:
	@echo "Running Python unit tests..."
	uv run pytest tests/unit --cov=src --cov-fail-under=100 -v

# TypeScript unit tests
test-frontend:
	@echo "Running TypeScript unit tests..."
	cd frontend && npm run test:coverage

# E2E tests
test-e2e:
	@echo "Running E2E tests..."
	cd frontend && npm run test:e2e

# Integration tests
test-integration:
	@echo "Running integration tests..."
	uv run pytest tests/integration -v

# Run all tests
test-all: test test-frontend test-integration test-e2e

# Python linting and type checking
lint-python:
	@echo "Running mypy..."
	uv run mypy src/
	@echo "Running ruff check..."
	uv run ruff check src/ tests/

# TypeScript linting and type checking
lint-frontend:
	@echo "Running eslint..."
	cd frontend && npm run lint
	@echo "Running TypeScript type check..."
	cd frontend && npm run typecheck

# All linting
lint: lint-python lint-frontend

# Type checking only
typecheck:
	@echo "Running mypy..."
	uv run mypy src/
	@echo "Running TypeScript type check..."
	cd frontend && npm run typecheck

# Format Python code
format-python:
	@echo "Formatting Python code..."
	uv run isort src/ tests/
	uv run ruff format src/ tests/

# Format TypeScript code
format-frontend:
	@echo "Formatting TypeScript code..."
	cd frontend && npm run format

# Format all code
format: format-python format-frontend

# Run tflint on infrastructure code
tflint:
	@echo "Running tflint on OpenTofu code..."
	cd tofu && tflint --init
	cd tofu && tflint --recursive

# Run KICS security scan
kics:
	@echo "Pulling latest KICS image..."
	docker pull checkmarx/kics:latest
	@echo "Running KICS security scan..."
	@mkdir -p tofu/kics-results
	docker run -t \
		-v "$(PWD)/tofu":/path:ro,z \
		-v "$(PWD)/tofu/kics-results":/results:z \
		checkmarx/kics scan \
		-p /path \
		-o /results \
		--config /path/.kics.yml
	@echo "KICS results saved to tofu/kics-results/"

# All infrastructure checks (linting only, no deployment)
lint-infra: tflint kics

# Run everything (development workflow)
all: format lint typecheck test test-frontend

# CI pipeline (no formatting, just validation)
ci: lint typecheck test test-frontend test-integration

# Clean generated files
clean:
	@echo "Cleaning generated files..."
	rm -rf htmlcov/
	rm -rf .coverage
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf frontend/coverage/
	rm -rf frontend/playwright-report/
	rm -rf frontend/test-results/
	rm -rf tofu/kics-results/
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".vitest" -exec rm -rf {} + 2>/dev/null || true
	@echo "Clean complete!"
