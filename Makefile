# Development entry points. Every target is also what CI runs, so a green local
# run means a green pipeline.

.DEFAULT_GOAL := help
UV := uv
# Root needs no sudo, and on a minimal server sudo may not be installed at all.
SUDO := $(shell [ "$$(id -u)" = 0 ] || echo sudo)

.PHONY: help setup format lint typecheck test test-unit test-integration audit check \
        stack-up stack-down stack-logs stack-verify migrate accept console inspect \
        record-install record-status record-stop clean \
        ladder history history-all history-long history-longest history-status history-table funding funding-all sentiment news information chart signal signal-all paper paper-report paper-tick paper-install paper-status paper-stop evaluate evaluate-all evaluate-report evaluate-push evaluate-summary

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

testnet-account: ## What the testnet account holds: equity, positions, open orders
	$(UV) run python -m services.execution_engine.cli --account

testnet-check: ## Decide an order and show it, without sending anything (SIDE, NOTIONAL)
	$(UV) run python -m services.execution_engine.cli --check \
		--side $(or $(SIDE),BUY) --notional $(or $(NOTIONAL),20)

testnet-order: ## Actually place one test order on testnet (SIDE, NOTIONAL)
	$(UV) run python -m services.execution_engine.cli \
		--side $(or $(SIDE),BUY) --notional $(or $(NOTIONAL),20)

testnet-cancel: ## Cancel a test order by its client order id (ID=...)
	$(UV) run python -m services.execution_engine.cli --cancel $(ID)

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

explain-gaps: ## Print the raw timestamps behind the first few open gaps
	$(UV) run python infrastructure/scripts/close_resolved_gaps.py --explain $(or $(N),3)

strategy: ## Run the baseline strategies over recorded data (HOURS, HOLD, THRESHOLD)
	$(UV) run python -m services.strategy_engine.evaluate_cli \
		--hours $(or $(HOURS),24) --hold $(or $(HOLD),30) \
		--threshold $(or $(THRESHOLD),0.30)

history: ## Download price history (ASSET, INTERVAL, DAYS, SOURCE=binance for years of it)
	$(UV) run python -m services.research.history_cli \
		--asset $(or $(ASSET),SOL) --interval $(or $(INTERVAL),1h) \
		--days $(or $(DAYS),730) --source $(or $(SOURCE),hyperliquid)

evaluate: ## Run a rule against its controls (ASSET, INTERVAL, RULE, SHUFFLES, VENUE, DAYS, HALVES=1, HOLDOUT=1)
	$(UV) run python -m services.strategy_engine.evaluate_candles_cli \
		--asset $(or $(ASSET),SOL) --interval $(or $(INTERVAL),4h) \
		--rule $(or $(RULE),trend-following) --shuffles $(or $(SHUFFLES),20) \
		--venue $(or $(VENUE),hyperliquid) --days $(or $(DAYS),730) \
		--periods $(or $(PERIODS),0) \
		$(if $(HALVES),--halves,) $(if $(HOLDOUT),--holdout,)

evaluate-summary: ## Compress the newest evaluation to one line per run, small enough to send
	@$(UV) run python infrastructure/scripts/summarize_evaluation.py $(FILE)

evaluate-push: ## Commit and push evaluations already written, without re-running them
	git add docs/evidence/build-0.1/evaluations
	@git diff --cached --quiet && echo "nothing new to push" || \
		git -c user.name="recording host" -c user.email="recorder@localhost" \
			commit -q -m "Strategy evaluation results" -- docs/evidence/build-0.1/evaluations
	@GIT_TERMINAL_PROMPT=0 git push origin $$(git rev-parse --abbrev-ref HEAD)

evaluate-report: ## Run every rule on both assets, write it into the repo and push it
	@HOLDOUT=$(or $(HOLDOUT),0) PUSH=$(or $(PUSH),1) UV=$(UV) \
		bash infrastructure/scripts/publish_evaluation.sh

evaluate-all: ## Run one unchanged rule across assets (ASSETS, INTERVAL, RULE, SHUFFLES, HALVES=1)
	@for asset in $(or $(ASSETS),BTC ETH SOL BNB); do \
		$(UV) run python -m services.strategy_engine.evaluate_candles_cli \
			--asset $$asset --interval $(or $(INTERVAL),4h) \
			--rule $(or $(RULE),trend-following) --shuffles $(or $(SHUFFLES),20) \
			--venue $(or $(VENUE),hyperliquid) --days $(or $(DAYS),730) \
			--periods $(or $(PERIODS),0) \
			$(if $(HALVES),--halves,) || exit 1; \
		echo; \
	done

paper: ## One paper-trading tick by hand (ASSET, INTERVAL, VENUE, RULE, DRY=1)
	$(UV) run python -m services.strategy_engine.paper_cli \
		--asset $(or $(ASSET),BTC) --interval $(or $(INTERVAL),4h) \
		--venue $(or $(VENUE),binance) --rule $(or $(RULE),funding-extreme) \
		$(if $(DRY),--dry-run,)

paper-report: ## What the paper trader has done and what it is holding
	@$(UV) run python -m services.strategy_engine.paper_report_cli

paper-tick: ## One full turn of the loop by hand: refresh, decide, report, push
	@bash infrastructure/scripts/paper_tick.sh

paper-install: ## Install the timer that runs the loop every 4 hours, by itself
	$(SUDO) cp infrastructure/systemd/stw-paper.service /etc/systemd/system/
	$(SUDO) cp infrastructure/systemd/stw-paper.timer /etc/systemd/system/
	$(SUDO) systemctl daemon-reload
	$(SUDO) systemctl enable --now stw-paper.timer
	@$(SUDO) systemctl --no-pager list-timers stw-paper.timer

paper-status: ## When did the loop last run, and what did it say?
	@$(SUDO) systemctl --no-pager list-timers stw-paper.timer
	@echo
	@$(SUDO) journalctl -u stw-paper -n 40 --no-pager

paper-stop: ## Stop the loop and leave it stopped across reboots
	$(SUDO) systemctl disable --now stw-paper.timer

signal: ## What the bot thinks right now, with reasons (ASSET, INTERVAL, VENUE)
	$(UV) run python -m services.strategy_engine.signal_cli \
		--asset $(or $(ASSET),SOL) --interval $(or $(INTERVAL),4h) \
		--venue $(or $(VENUE),binance)

signal-all: ## The same, for every asset in the Phase 1 universe
	@for asset in BTC ETH SOL BNB; do \
		$(UV) run python -m services.strategy_engine.signal_cli \
			--asset $$asset --interval $(or $(INTERVAL),4h) \
			--venue $(or $(VENUE),binance) | head -14; \
		echo; \
	done

chart: ## Print how the Feature Engine reads the chart now (ASSET, INTERVAL)
	$(UV) run python -m services.strategy_engine.chart_cli \
		--asset $(or $(ASSET),SOL) --interval $(or $(INTERVAL),4h)

history-all: ## Download history for the Phase 1 universe (ASSETS, DAYS, SOURCE, INTERVALS)
	@for asset in $(or $(ASSETS),BTC ETH SOL BNB); do \
		for interval in $(or $(INTERVALS),1h 4h 1d); do \
			echo "--- $$asset $$interval ---"; \
			$(UV) run python -m services.research.history_cli \
				--asset $$asset --interval $$interval --days $(or $(DAYS),730) \
				--source $(or $(SOURCE),hyperliquid) || exit 1; \
			echo; \
		done; \
	done

history-long: ## Download years of 4h history from Binance, for the regime question
	@$(MAKE) --no-print-directory history-all \
		SOURCE=binance INTERVALS=4h DAYS=$(or $(DAYS),2200)

history-longest: ## Nine years of 4h history and funding, for BTC ETH BNB (SOL lists 2020)
	@$(MAKE) --no-print-directory history-all \
		ASSETS="BTC ETH BNB" SOURCE=binance INTERVALS=4h DAYS=$(or $(DAYS),3300)
	@$(MAKE) --no-print-directory funding-all \
		ASSETS="BTC ETH BNB" DAYS=$(or $(DAYS),3300)

sentiment: ## Download the Fear & Greed index: eight years, free, no key
	$(UV) run python -m services.research.information_cli --what sentiment

news: ## Collect current headlines from the outlets' RSS feeds
	$(UV) run python -m services.research.information_cli --what headlines

information: ## Both of the above, and what is stored
	$(UV) run python -m services.research.information_cli

funding: ## Download funding-rate history: positioning, not pattern (ASSET, DAYS)
	$(UV) run python -m services.research.funding_cli \
		--asset $(or $(ASSET),SOL) --days $(or $(DAYS),2200)

funding-all: ## The same for every asset in the Phase 1 universe
	@for asset in $(or $(ASSETS),BTC ETH SOL BNB); do \
		$(UV) run python -m services.research.funding_cli \
			--asset $$asset --days $(or $(DAYS),2200) | tail -8 || exit 1; \
		echo; \
	done

history-table: ## One line per stored series: what history this project holds
	@$(UV) run python -m services.research.history_cli --inventory

history-status: ## What history is already stored, without downloading (ASSET, INTERVAL)
	$(UV) run python -m services.research.history_cli \
		--asset $(or $(ASSET),SOL) --interval $(or $(INTERVAL),1h) \
		--days $(or $(DAYS),730) --read-only

ladder: ## How far price moves at each horizon, against the cost floors (HOURS)
	$(UV) run python -m services.research.calibrate_cli \
		--hours $(or $(HOURS),24) --ladder

close-gaps: ## Close silences the store shows ended (read-only; APPLY=1 to write)
	$(UV) run python infrastructure/scripts/close_resolved_gaps.py --record-outages $(if $(APPLY),--apply,)

watch: ## Ask the store once whether the recorder is still receiving
	$(UV) run python infrastructure/scripts/watch_recording.py --no-restart

watch-test-email: ## Send one test alert, to prove the mail path works before it matters
	$(UV) run python infrastructure/scripts/watch_recording.py --test-email

watch-install: ## Install the timer that asks that question every five minutes
	$(SUDO) cp infrastructure/systemd/stw-watchdog.service /etc/systemd/system/
	$(SUDO) cp infrastructure/systemd/stw-watchdog.timer /etc/systemd/system/
	$(SUDO) systemctl daemon-reload
	$(SUDO) systemctl enable --now stw-watchdog.timer
	@$(SUDO) systemctl --no-pager list-timers stw-watchdog.timer

watch-status: ## When did the watchdog last look, and what did it find?
	@$(SUDO) systemctl --no-pager list-timers stw-watchdog.timer
	@echo
	@$(SUDO) journalctl -u stw-watchdog -n 20 --no-pager

record-status: ## Is the recorder alive, and what has it said lately?
	@$(SUDO) systemctl --no-pager --lines=0 status stw-recorder | head -8
	@echo
	@$(SUDO) journalctl -u stw-recorder -n 15 --no-pager

record-stop: ## Stop the recorder and leave it stopped across reboots
	$(SUDO) systemctl disable --now stw-recorder

clean: ## Remove caches and build artifacts
	rm -rf .mypy_cache .ruff_cache .pytest_cache htmlcov .coverage coverage.xml requirements-audit.txt
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
