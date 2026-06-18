.PHONY: dev test lint evals evals-golden migrate build help

BACKEND_DIR := backend
COMPOSE := docker compose

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

dev: ## Start all services with docker-compose
	$(COMPOSE) up --build

dev-down: ## Stop all services
	$(COMPOSE) down

dev-logs: ## Tail backend logs
	$(COMPOSE) logs -f backend

test: ## Run backend test suite
	cd $(BACKEND_DIR) && python -m pytest tests/ -v --cov=app --cov-report=term-missing

lint: ## Run ruff linter + mypy type checker
	cd $(BACKEND_DIR) && python -m ruff check app/ tests/ && python -m mypy app/

migrate: ## Run database migrations against local postgres
	docker compose exec postgres psql -U postgres -d travelcopilot -f /dev/stdin < $(BACKEND_DIR)/migrations/001_initial.sql

evals: ## Run Langfuse evals (requires LANGFUSE_* env vars)
	cd $(BACKEND_DIR) && python -m pytest tests/evals/ -v -m "not golden"

evals-golden: ## Run golden-set evals
	cd $(BACKEND_DIR) && python -m pytest tests/evals/ -v -m golden

build: ## Build backend Docker image
	docker build -t travelcopilot-backend $(BACKEND_DIR)/
