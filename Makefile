# Development entry points. Every target is also what CI runs, so a green local
# run means a green pipeline.

.DEFAULT_GOAL := help
UV := uv

.PHONY: help setup format lint typecheck test test-unit audit check stack-up stack-down stack-logs clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## Create the virtualenv and install all dependencies
	$(UV) sync --extra dev

format: ## Apply formatting
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

lint: ## Check formatting and lint rules
	$(UV) run ruff format --check .
	$(UV) run ruff check .

typecheck: ## Run mypy in strict mode
	$(UV) run mypy libs services tests

test-unit: ## Run unit and security tests only
	$(UV) run pytest tests/unit tests/security

test: ## Run the full test suite with coverage
	$(UV) run pytest --cov --cov-report=term-missing

audit: ## Check locked dependencies for known vulnerabilities
	$(UV) export --extra dev --no-emit-project --format requirements.txt > requirements-audit.txt
	$(UV) run pip-audit --strict --requirement requirements-audit.txt
	@rm -f requirements-audit.txt

check: lint typecheck test ## Everything CI runs

stack-up: ## Start the local storage stack (M1)
	docker compose -f infrastructure/docker/docker-compose.yml up -d

stack-down: ## Stop the local storage stack
	docker compose -f infrastructure/docker/docker-compose.yml down

stack-logs: ## Follow storage stack logs
	docker compose -f infrastructure/docker/docker-compose.yml logs -f

clean: ## Remove caches and build artifacts
	rm -rf .mypy_cache .ruff_cache .pytest_cache htmlcov .coverage coverage.xml requirements-audit.txt
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
