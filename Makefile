.PHONY: dev dev-down dev-logs test lint lint-fix format format-check check-deps \
	package docker-build build verify evals evals-golden migrate help \
	frontend-install frontend-dev frontend-lint frontend-typecheck frontend-test \
	frontend-build frontend-docker-build

BACKEND_DIR := backend
FRONTEND_DIR := frontend
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

dev: ## Start backend and frontend with root Docker Compose
	$(call banner,Starting TravelCopilot backend and frontend)
	$(COMPOSE) up --build

dev-down: ## Stop all services
	$(call banner,Stopping TravelCopilot dev stack)
	$(COMPOSE) down

dev-logs: ## Tail backend and frontend logs
	$(COMPOSE) logs -f backend frontend

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

frontend-install: ## Install frontend dependencies
	cd $(FRONTEND_DIR) && npm install

frontend-dev: ## Run the frontend dev server on port 3001
	cd $(FRONTEND_DIR) && npm run dev

frontend-lint: ## Lint the frontend
	cd $(FRONTEND_DIR) && npm run lint

frontend-typecheck: ## Type-check the frontend
	cd $(FRONTEND_DIR) && npm run typecheck

frontend-test: ## Run frontend unit tests
	cd $(FRONTEND_DIR) && npm run test

frontend-build: ## Production build of the frontend
	cd $(FRONTEND_DIR) && npm run build

frontend-docker-build: ## Build frontend Docker image
	docker build -t travelcopilot-frontend $(FRONTEND_DIR)/

build: package docker-build frontend-build frontend-docker-build ## Build backend + frontend artifacts and Docker images
	@printf "$(GREEN)$(BOLD)==> Build complete$(RESET)\n"

verify: ## Auto-fix, validate, test, and build backend + frontend artifacts
	$(call banner,Running full verify pipeline)
	$(MAKE) check-deps
	$(MAKE) frontend-install
	$(MAKE) format
	$(MAKE) lint-fix
	$(MAKE) format-check
	$(MAKE) lint
	$(MAKE) frontend-lint
	$(MAKE) frontend-typecheck
	$(MAKE) test
	$(MAKE) frontend-test
	$(MAKE) build
	@printf "$(GREEN)$(BOLD)==> Verify pipeline passed$(RESET)\n"
