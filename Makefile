.DEFAULT_GOAL := help
SHELL := /bin/bash

# Tooling
PY ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
COMPOSE ?= docker compose

# Remote server (an alias from ~/.ssh/config; "Host miles web" defines the aliases "miles" and "web")
REMOTE ?= miles
REMOTE_DIR ?= /opt/storyquest
IMAGE ?= storyquest:latest
DEPLOY_PLATFORM ?= linux/amd64
VIEWER_PORT ?= 8001
SERVICE ?=

# Task parameters
BOOK ?=
MODE ?= M1
SPLIT ?= dev
RUN ?=
RUNS ?=
DATA ?=
DB ?= content

# Load config.env (committed settings) then .env (secrets) for the recipe's shell.
ENV := set -a; [ -f config.env ] && . ./config.env; [ -f .env ] && . ./.env; set +a;

.PHONY: help setup doctor llm-ping \
        dev dev-api dev-worker dev-web up down logs ps build \
        test lint format typecheck check check-data \
        migrate seed admin-user ingest inspect db-shell db-viewer db-reset \
        eval eval-report eval-compare \
        deploy remote-ps remote-logs remote-restart remote-shell remote-viewer remote-db-tunnel remote-db-pull \
        clean clean-all _need-code _need-web _need-compose _need-book

##@ Getting started

help: ## Show this help
	@awk 'BEGIN{FS=":.*##"; printf "\nUsage: make \033[36m<target>\033[0m [VAR=value]\n"} \
	  /^##@/{printf "\n\033[1m%s\033[0m\n", substr($$0,5)} \
	  /^[a-zA-Z_-]+:.*##/{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf "\nCommon variables: BOOK=<id> MODE=<M0..M5> SPLIT=<dev|test> RUN=<run dir> DB=<content|app> DATA=<dir> REMOTE=<ssh alias> SERVICE=<name>\n\n"

setup: ## First-time setup: .env, Python venv, dependencies, web packages
	@test -f .env || { cp .env.example .env; echo "Created .env: fill in LLM_API_KEY and SESSION_SECRET"; }
	@test -d $(VENV) || $(PY) -m venv $(VENV)
	@if [ -f pyproject.toml ]; then $(BIN)/pip install -q -e ".[dev]"; else echo "skip Python deps: no pyproject.toml yet"; fi
	@if [ -f web/package.json ]; then npm --prefix web install; else echo "skip web deps: no web/ yet"; fi

doctor: ## Check tools, secrets, CA certificate and config
	@for t in python3 docker npm sqlite3 curl ssh rsync; do command -v $$t >/dev/null && echo "ok       $$t" || echo "MISSING  $$t"; done
	@$(ENV) \
	  [ -n "$$LLM_API_KEY" ] && echo "ok       LLM_API_KEY is set" || echo "MISSING  LLM_API_KEY (put it in .env)"; \
	  [ -f "$$LLM_CA_CERT_PATH" ] && echo "ok       CA certificate at $$LLM_CA_CERT_PATH" || echo "MISSING  CA certificate at $$LLM_CA_CERT_PATH"; \
	  echo "config   $$LLM_PROVIDER $$LLM_MODEL via $$LLM_BASE_URL"

llm-ping: ## Send a tiny request to the model endpoint to verify key, certificate and URL
	@$(ENV) curl -sS --cacert "$$LLM_CA_CERT_PATH" "$$LLM_BASE_URL/chat/completions" \
	  -H "Authorization: Bearer $$LLM_API_KEY" -H "Content-Type: application/json" \
	  -d "{\"model\":\"$$LLM_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hi in three words.\"}],\"max_tokens\":16}" \
	  -w '\nHTTP %{http_code}\n'

##@ Run

dev: _need-code _need-web ## Run API, worker and web dev server together (hot reload)
	@$(MAKE) -j3 --output-sync=target dev-api dev-worker dev-web

dev-api: _need-code ## Run the API with reload
	@$(ENV) $(BIN)/uvicorn storyquest.api.main:app --reload --port "$${API_PORT:-8000}"

dev-worker: _need-code ## Run the ingestion worker
	@$(ENV) $(BIN)/storyquest worker

dev-web: _need-web ## Run the React dev server
	@npm --prefix web run dev

up: _need-compose ## Start the stack in Docker (app + worker); add PROFILE=admin via COMPOSE_PROFILES
	@$(COMPOSE) up --build

down: _need-compose ## Stop the Docker stack
	@$(COMPOSE) down

logs: _need-compose ## Follow Docker logs (SERVICE=app to filter)
	@$(COMPOSE) logs -f --tail=200 $(SERVICE)

ps: _need-compose ## Show Docker service status
	@$(COMPOSE) ps

build: _need-compose ## Build the Docker image
	@$(COMPOSE) build

##@ Quality

check-data: ## Validate the golden set and the reference spine
	@$(PY) eval/check_data.py

test: _need-code ## Run backend and web tests
	@$(BIN)/pytest
	@if [ -f web/package.json ]; then npm --prefix web test --if-present; fi

lint: _need-code ## Lint backend and web
	@$(BIN)/ruff check src tests
	@if [ -f web/package.json ]; then npm --prefix web run lint --if-present; fi

format: _need-code ## Auto-format backend code
	@$(BIN)/ruff format src tests

typecheck: _need-code ## Type-check backend code
	@$(BIN)/mypy src

check: check-data lint typecheck test ## Everything CI would run

##@ Data and ingestion

migrate: _need-code ## Apply database migrations
	@$(ENV) $(BIN)/storyquest db migrate

seed: _need-code ## Import the fixture books (Jungle Book) into the local database
	@$(ENV) $(BIN)/storyquest catalog import eval/books

admin-user: _need-code ## Create an admin user (prompts for details)
	@$(ENV) $(BIN)/storyquest admin create-user

ingest: _need-code _need-book ## Ingest a book: make ingest BOOK=<id>
	@$(ENV) $(BIN)/storyquest ingest $(BOOK)

inspect: _need-code _need-book ## Print chapters, beats and chunk counts: make inspect BOOK=<id>
	@$(ENV) $(BIN)/storyquest inspect $(BOOK)

db-shell: ## Open sqlite3 on a local database: make db-shell DB=content|app
	@$(ENV) sqlite3 "$${DATA_DIR:-var}/$(DB).db"

db-viewer: ## Browse local databases in Datasette (DATA=dir to point at a snapshot)
	@$(ENV) d="$(DATA)"; d="$${d:-$$DATA_DIR}"; \
	  test -x $(BIN)/datasette || { echo "datasette not installed: run make setup"; exit 1; }; \
	  echo "Viewer: http://localhost:$(VIEWER_PORT)"; \
	  $(BIN)/datasette serve "$$d/content.db" "$$d/app.db" --port $(VIEWER_PORT)

db-reset: ## DELETE the local databases (asks first); books and LLM cache are kept
	@$(ENV) read -p "Delete $$DATA_DIR/content.db and app.db? [y/N] " a; \
	  [ "$$a" = y ] && rm -f "$$DATA_DIR"/content.db* "$$DATA_DIR"/app.db* && echo "Deleted." || echo "Cancelled."

##@ Evaluation

eval: _need-code ## Run the golden set: make eval MODE=M1 SPLIT=dev
	@$(ENV) $(BIN)/storyquest eval run --mode $(MODE) --split $(SPLIT)

eval-report: _need-code ## Build the HTML report for a run: make eval-report RUN=eval/runs/<id>
	@test -n "$(RUN)" || { echo "usage: make eval-report RUN=eval/runs/<id>"; exit 1; }
	@$(ENV) $(BIN)/storyquest eval report $(RUN)

eval-compare: _need-code ## Compare runs side by side: make eval-compare RUNS="eval/runs/a eval/runs/b"
	@test -n "$(RUNS)" || { echo "usage: make eval-compare RUNS=\"eval/runs/a eval/runs/b\""; exit 1; }
	@$(ENV) $(BIN)/storyquest eval compare $(RUNS)

##@ Remote server (SSH alias in REMOTE, default "miles")

deploy: _need-compose ## Build the image, ship it over SSH and restart the stack
	DOCKER_DEFAULT_PLATFORM=$(DEPLOY_PLATFORM) $(COMPOSE) build
	docker save $(IMAGE) | gzip | ssh $(REMOTE) 'gunzip | docker load'
	ssh $(REMOTE) 'mkdir -p $(REMOTE_DIR)'
	rsync -az --relative docker-compose.yml config.env config.prod.env $$(test -d certs && echo certs) $(REMOTE):$(REMOTE_DIR)/
	ssh $(REMOTE) 'cd $(REMOTE_DIR) && test -f .env || { echo "Create $(REMOTE_DIR)/.env with the secrets first"; exit 1; }; docker compose up -d'

remote-ps: ## Show service status on the server
	@ssh $(REMOTE) 'cd $(REMOTE_DIR) && docker compose ps'

remote-logs: ## Follow server logs (SERVICE=app to filter)
	@ssh $(REMOTE) 'cd $(REMOTE_DIR) && docker compose logs -f --tail=200 $(SERVICE)'

remote-restart: ## Restart the stack on the server
	@ssh $(REMOTE) 'cd $(REMOTE_DIR) && docker compose restart $(SERVICE)'

remote-shell: ## Open a shell in the app container on the server
	@ssh -t $(REMOTE) 'cd $(REMOTE_DIR) && docker compose exec app sh'

remote-viewer: ## Start the read-only DB viewer on the server (localhost only there)
	@ssh $(REMOTE) 'cd $(REMOTE_DIR) && docker compose --profile admin up -d dbviewer'

remote-db-tunnel: ## Tunnel to the server's DB viewer, then open http://localhost:$(VIEWER_PORT)
	@echo "Viewer: http://localhost:$(VIEWER_PORT)  (Ctrl-C to close)"
	@ssh -N -L $(VIEWER_PORT):127.0.0.1:$(VIEWER_PORT) $(REMOTE)

remote-db-pull: ## Copy a consistent snapshot of the server databases to var/remote-snapshot
	@ssh $(REMOTE) 'cd $(REMOTE_DIR) && docker compose exec -T app storyquest db backup /data/backups/latest'
	@mkdir -p var/remote-snapshot
	@rsync -az $(REMOTE):$(REMOTE_DIR)/var/backups/latest/ var/remote-snapshot/
	@echo "Snapshot in var/remote-snapshot. Browse it: make db-viewer DATA=var/remote-snapshot"

##@ Cleanup

clean: ## Remove caches and build output
	@find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null; \
	  rm -rf .pytest_cache .ruff_cache .mypy_cache web/dist

clean-all: clean ## Also remove the venv and web dependencies
	@rm -rf $(VENV) web/node_modules

# Guards: fail with a clear message while the code does not exist yet.
_need-code:
	@test -d src/storyquest || { echo "Not available yet: src/storyquest does not exist (see docs/design)."; exit 1; }
_need-web:
	@test -d web || { echo "Not available yet: web/ does not exist (see docs/design)."; exit 1; }
_need-compose:
	@test -f docker-compose.yml || { echo "Not available yet: docker-compose.yml does not exist (see docs/design/08)."; exit 1; }
_need-book:
	@test -n "$(BOOK)" || { echo "usage: make <target> BOOK=<gutenberg id>"; exit 1; }
