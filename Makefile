.PHONY: dev dev-down dev-logs test lint lint-fix format format-check check-deps \
	package docker-build build verify evals evals-golden migrate help

BACKEND_DIR := backend
COMPOSE := docker compose

# ── Terminal colors for section banners ─────────────────────────────────────
CYAN := \033[36m
GREEN := \033[32m
YELLOW := \033[33m
BOLD := \033[1m
RESET := \033[0m
define banner
	@printf "$(CYAN)$(BOLD)==> %s$(RESET)\n" "$(1)"
endef

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

dev: ## Start all services with docker-compose
	$(call banner,Starting TravelCopilot dev stack)
	$(COMPOSE) up --build

dev-down: ## Stop all services
	$(call banner,Stopping TravelCopilot dev stack)
	$(COMPOSE) down

dev-logs: ## Tail backend logs
	$(COMPOSE) logs -f backend

test: ## Run backend test suite
	$(call banner,Running backend test suite)
	cd $(BACKEND_DIR) && uv run pytest tests/ -v --cov=app --cov-report=term-missing

format: ## Auto-format code with ruff
	cd $(BACKEND_DIR) && uv run ruff format app/ tests/

format-check: ## Check formatting without modifying files (used in CI)
	cd $(BACKEND_DIR) && uv run ruff format --check app/ tests/

lint: ## Run ruff linter + mypy type checker
	$(call banner,Linting backend (ruff + mypy))
	cd $(BACKEND_DIR) && uv run ruff check app/ tests/ && uv run mypy app/

lint-fix: ## Auto-fix ruff lint issues where possible
	cd $(BACKEND_DIR) && uv run ruff check --fix app/ tests/

check-deps: ## Verify lockfile and sync all backend dependencies
	cd $(BACKEND_DIR) && uv lock --check && uv sync --locked --all-groups

migrate: ## Run database migrations against local postgres
	$(call banner,Applying database migrations)
	docker compose exec -T postgres psql -U postgres -d travelcopilot -f /dev/stdin < $(BACKEND_DIR)/migrations/001_initial.sql

evals: ## Run Langfuse evals (requires LANGFUSE_* env vars)
	cd $(BACKEND_DIR) && uv run pytest tests/evals/ -v -m "not golden"

evals-golden: ## Run golden-set evals
	cd $(BACKEND_DIR) && uv run pytest tests/evals/ -v -m golden

package: ## Build backend Python wheel and source distribution
	cd $(BACKEND_DIR) && uv build --clear

docker-build: ## Build backend Docker image
	docker build -t travelcopilot-backend $(BACKEND_DIR)/

build: package docker-build ## Build backend Python package and Docker image
	@printf "$(GREEN)$(BOLD)==> Build complete$(RESET)\n"

verify: ## Auto-fix, validate, test, and build backend artifacts
	$(call banner,Running full verify pipeline)
	$(MAKE) check-deps
	$(MAKE) format
	$(MAKE) lint-fix
	$(MAKE) format-check
	$(MAKE) lint
	$(MAKE) test
	$(MAKE) build
	@printf "$(GREEN)$(BOLD)==> Verify pipeline passed$(RESET)\n"
