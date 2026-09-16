# Development entry points. Every target is also what CI runs, so a green local
# run means a green pipeline.

.DEFAULT_GOAL := help
UV := uv
# Root needs no sudo, and on a minimal server sudo may not be installed at all.
SUDO := $(shell [ "$$(id -u)" = 0 ] || echo sudo)

.PHONY: help setup format lint typecheck test test-unit test-integration audit check \
        stack-up stack-down stack-logs stack-verify migrate accept console inspect \
        record-install record-status record-stop clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## Create the virtualenv, install dependencies, and seed .env
	$(UV) sync --extra dev
	@# Without a .env the store credentials fall back to their defaults, which
	@# are empty — so an application authenticates against a stack started with
	@# real local passwords and gets AUTHENTICATION_FAILED. The example holds
	@# development values that are deliberately visible, so copying it is safe;
	@# an existing .env is never touched.
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "created .env from .env.example (local development values)"; \
	fi

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

test: ## Run the full test suite with coverage (skips integration)
	$(UV) run pytest --cov --cov-report=term-missing -m "not integration"

test-integration: ## Run integration tests against the running stack
	$(UV) run pytest tests/integration -m integration

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

stack-verify: ## Check every store is reachable and correctly configured
	$(UV) run python infrastructure/scripts/verify_stack.py

migrate: ## Verify the stack, then apply pending migrations
	$(UV) run python infrastructure/scripts/verify_stack.py --migrate

console: ## Serve the product console on http://localhost:8000
	$(UV) run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload

accept: ## Run the full M1/M2 acceptance against the real stack and the live venue
	@bash infrastructure/scripts/accept_m1_m2.sh $(ACCEPT_ARGS)

inspect: ## Report what the store actually holds from the last HOURS (default 24)
	$(UV) run python infrastructure/scripts/inspect_recording.py --hours $(or $(HOURS),24)

report: ## Write what the store holds into the repo and push it (HOURS=24, PUSH=1)
	@HOURS=$(or $(HOURS),24) PUSH=$(or $(PUSH),1) UV=$(UV) bash infrastructure/scripts/publish_recording_report.sh

record-install: ## Install and start the recorder as a service that outlives the shell
	$(SUDO) cp infrastructure/systemd/stw-recorder.service /etc/systemd/system/
	$(SUDO) systemctl daemon-reload
	$(SUDO) systemctl enable --now stw-recorder
	@sleep 5
	@$(SUDO) systemctl --no-pager --lines=0 status stw-recorder | head -6
	@echo
	@$(MAKE) --no-print-directory inspect HOURS=1

record-status: ## Is the recorder alive, and what has it said lately?
	@$(SUDO) systemctl --no-pager --lines=0 status stw-recorder | head -8
	@echo
	@$(SUDO) journalctl -u stw-recorder -n 15 --no-pager

record-stop: ## Stop the recorder and leave it stopped across reboots
	$(SUDO) systemctl disable --now stw-recorder

clean: ## Remove caches and build artifacts
	rm -rf .mypy_cache .ruff_cache .pytest_cache htmlcov .coverage coverage.xml requirements-audit.txt
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
