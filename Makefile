.DEFAULT_GOAL := help

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Install Python dev dependencies
	pip install -r agent/requirements.txt
	pip install ruff black mypy pytest pytest-cov

lint: ## Run all linters
	ruff check agent/
	black --check agent/
	mypy agent/ --ignore-missing-imports
	terraform fmt -check terraform/ || true
	hadolint Dockerfile || true

test: ## Run tests with coverage
	pytest agent/tests/ -v --cov=agent --cov-report=term-missing

build: ## Build Docker image
	docker build -t kagent-healer:local .

run: ## Run agent locally (requires .env)
	docker-compose up

demo: ## Run end-to-end demo (chaos injection + healing loop)
	./scripts/demo.sh

port-forward: ## Open all service tunnels (Grafana, Prometheus, Alertmanager, KAgent UI)
	./scripts/port-forward.sh

teardown: ## Destroy everything in correct order (asks for confirmation)
	./scripts/teardown.sh

.PHONY: help install lint test build run demo port-forward teardown
