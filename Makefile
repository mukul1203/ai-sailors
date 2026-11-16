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
MODES ?= M0 M1S M2S
SPLIT ?= dev
RUN ?=
DATA ?=
DB ?= content

ARGS ?=
Q ?=

# Load .env (secrets) then config.env (settings) into the recipe's shell.
# Variables already set in the caller's environment win, matching the app's own precedence.
HASH := \#
ENV := set -a; \
	load() { [ -f "$$1" ] || return 0; \
	  while IFS='=' read -r k v; do \
	    case "$$k" in ''|"$(HASH)"*) continue;; esac; \
	    v="$${v//\"/}"; \
	    [ -z "$${!k+x}" ] && export "$$k=$$v"; \
	  done < "$$1"; return 0; }; \
	load .env; load config.env; set +a;

.PHONY: help setup doctor llm-ping \
        dev dev-api dev-worker dev-web build-web up down logs ps build \
        test lint format typecheck check check-data \
        migrate seed demo-data admin-user ingest ingest-llm ingest-status review approve publish \
        entities worker embed inspect search ask db-shell db-viewer db-reset \
        eval eval-retrieval eval-report \
        deploy remote-ps remote-logs remote-restart remote-shell remote-viewer remote-db-tunnel remote-db-pull \
        clean clean-all _need-code _need-web _need-compose _need-book

##@ Getting started

# Prints every target that has a "## description" after its name, grouped by the "##@" headers.
help: ## Show this help
	@awk 'BEGIN{FS=":.*##"; printf "\nUsage: make \033[36m<target>\033[0m [VAR=value]\n"} \
	  /^##@/{printf "\n\033[1m%s\033[0m\n", substr($$0,5)} \
	  /^[a-zA-Z_-]+:.*##/{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf "\nCommon variables: BOOK=<id> MODE=<M0|M1|M1S|M2|M2S|M3|M3S> MODES=\"M0 M1 ...\" SPLIT=<dev|test> RUN=<run folder> DB=<content|app> DATA=<dir> REMOTE=<ssh alias> SERVICE=<name> Q=<question> ARGS=<extra options>\n\n"

# Creates .env from .env.example if missing, a .venv virtualenv, and installs the project with
# its dev tools (pip install -e ".[dev]"). Safe to re-run, e.g. after dependencies change.
setup: ## First-time setup: .env, Python venv, dependencies, web packages
	@test -f .env || { cp .env.example .env; echo "Created .env: fill in LLM_API_KEY and SESSION_SECRET"; }
	@test -d $(VENV) || $(PY) -m venv $(VENV)
	@if [ -f pyproject.toml ]; then $(BIN)/pip install -q -e ".[dev]"; else echo "skip Python deps: no pyproject.toml yet"; fi
	@if [ -f web/package.json ]; then npm --prefix web install; else echo "skip web deps: no web/ yet"; fi

# Read-only diagnostics: are the needed programs installed, are the secrets set, does the CA
# certificate file exist. Only says "set" or "MISSING"; never prints secret values.
doctor: ## Check tools, secrets, CA certificate and config
	@for t in python3 docker npm sqlite3 curl ssh rsync; do command -v $$t >/dev/null && echo "ok       $$t" || echo "MISSING  $$t"; done
	@$(ENV) \
	  [ -n "$$LLM_API_KEY" ] && echo "ok       LLM_API_KEY is set" || echo "MISSING  LLM_API_KEY (put it in .env)"; \
	  [ -n "$$LLM_BASE_URL" ] && echo "ok       LLM_BASE_URL is set" || echo "MISSING  LLM_BASE_URL (put it in .env)"; \
	  [ -f "$$LLM_CA_CERT_PATH" ] && echo "ok       CA certificate at $$LLM_CA_CERT_PATH" || echo "MISSING  CA certificate at $$LLM_CA_CERT_PATH"; \
	  if [ "$$EMBEDDING_PROVIDER" = gemini ]; then \
	    [ -n "$$GEMINI_API_KEY" ] && echo "ok       GEMINI_API_KEY is set" || echo "missing  GEMINI_API_KEY (only needed for hybrid modes M2 and M2S)"; \
	  else \
	    [ -n "$$EMBEDDING_API_KEY" ] && [ -n "$$EMBEDDING_BASE_URL" ] && echo "ok       EMBEDDING_API_KEY and EMBEDDING_BASE_URL are set" || echo "missing  EMBEDDING_API_KEY or EMBEDDING_BASE_URL (only needed for hybrid modes M2 and M2S)"; \
	    [ -f "$$EMBEDDING_CA_CERT_PATH" ] && echo "ok       embedding CA certificate at $$EMBEDDING_CA_CERT_PATH" || echo "missing  embedding CA certificate at $$EMBEDDING_CA_CERT_PATH (only needed for M2 and M2S)"; \
	  fi; \
	  echo "config   embeddings: $$EMBEDDING_PROVIDER $$EMBEDDING_MODEL ($$EMBEDDING_DIM dimensions)"; \
	  echo "config   $$LLM_PROVIDER $$LLM_MODEL"

# One tiny curl request straight to the model endpoint with your key, URL and certificate, so it
# tests the connection without our Python code. Prints the raw JSON; "HTTP 200" means it works.
llm-ping: ## Send a tiny request to the model endpoint to verify key, certificate and URL
	@$(ENV) curl -sS --cacert "$$LLM_CA_CERT_PATH" "$$LLM_BASE_URL/chat/completions" \
	  -H "Authorization: Bearer $$LLM_API_KEY" -H "Content-Type: application/json" \
	  -d "{\"model\":\"$$LLM_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hi in three words.\"}],\"max_tokens\":16}" \
	  -w '\nHTTP %{http_code}\n'

##@ Run

# Starts the API (with the web UI it serves) and the ingestion worker in parallel. There is no
# separate web dev server: the UI is plain files in src/storyquest/api/static.
dev: _need-code ## Run the API (and the UI it serves) and the ingestion worker together
	@$(MAKE) -j2 --output-sync=target dev-api dev-worker

# Serves the API and the child's web UI at http://localhost:$(API_PORT) (default 8000) and restarts
# when code changes. Uses the model for children's questions (PLAY_MODE in config.env; M2S needs
# `make embed`, otherwise it falls back to M1S). Books must be ingested, reviewed and published.
dev-api: _need-code ## Run the API and web UI with reload: http://localhost:8000
	@$(ENV) $(BIN)/uvicorn storyquest.api.main:create_app --factory --reload --port "$${API_PORT:-8000}"

# Processes queued ingestion jobs. Same as `make worker`.
dev-worker: _need-code ## Run the ingestion worker
	@$(ENV) $(BIN)/storyquest worker

# React app (web/): the dev server on :5173 proxies /api to `make dev-api` on :8000.
dev-web: _need-web ## Run the React dev server: http://localhost:5173 (needs make dev-api too)
	@npm --prefix web run dev

build-web: _need-web ## Build the React app into web/dist (the API serves it at :8000)
	@npm --prefix web install && npm --prefix web run build

# up, down, logs, ps and build are thin wrappers around `docker compose`. Not built yet.
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

# Checks eval/golden_v1.jsonl (fields, unique ids, valid values), the reference spine, that the
# Jungle Book file still matches its recorded hash, and that each evidence quote in the golden
# set appears at its cited raw line. Runs eval/check_data.py.
check-data: ## Validate the golden set and the reference spine
	@$(PY) eval/check_data.py

# Runs pytest. Tests that call the real model endpoint are marked "live" and skipped by default
# (run them on purpose with `.venv/bin/pytest -m live`).
test: _need-code ## Run backend and web tests
	@$(BIN)/pytest
	@if [ -f web/package.json ]; then npm --prefix web test --if-present; fi

# ruff check: style problems and common bugs. Does not change files (format does).
lint: _need-code ## Lint backend and web
	@$(BIN)/ruff check src tests
	@if [ -f web/package.json ]; then npm --prefix web run lint --if-present; fi

# ruff format: rewrites files to the project's code style.
format: _need-code ## Auto-format backend code
	@$(BIN)/ruff format src tests

# mypy in strict mode over src/: finds type mistakes without running the code.
typecheck: _need-code ## Type-check backend code
	@$(BIN)/mypy src

# check-data, lint, typecheck and test in that order, stopping at the first failure.
# Run before committing.
check: check-data lint typecheck test ## Everything CI would run

##@ Data and ingestion

# Creates content.db if it does not exist and applies any new SQL files from
# src/storyquest/stores/migrations/content/ (each file runs once and is recorded in
# schema_migrations). The other data commands do this automatically, so rarely needed by hand.
migrate: _need-code ## Apply database migrations
	@$(ENV) $(BIN)/storyquest db migrate

# Registers the books in eval/books/. For each folder with book.yaml and raw.txt it checks the
# file's sha256 against book.yaml, copies raw.txt to DATA_DIR/books/<id>/raw.txt, and adds or
# updates the book's row in content.db (an existing book keeps its status). Safe to re-run.
seed: _need-code ## Import the fixture books (Jungle Book) into the local database
	@$(ENV) $(BIN)/storyquest catalog import eval/books

# Everything needed to play with the Jungle Book in one go: seed, ingest (with the hand-written
# beats) and embed. Safe to re-run. The embed step is skipped, with a note, if there is no
# embedding key (EMBEDDING_API_KEY, or GEMINI_API_KEY for Gemini); modes M0, M1 and M1S work
# without it.
demo-data: _need-code ## Load the Jungle Book ready to play: seed, ingest with beats, embed
	@$(MAKE) --no-print-directory seed
	@$(MAKE) --no-print-directory ingest BOOK=236 ARGS="--spine eval/spine_mowgli_brothers.json"
	@$(ENV) if [ -n "$$EMBEDDING_API_KEY$$GEMINI_API_KEY" ]; then $(MAKE) --no-print-directory embed BOOK=236; \
	  else echo "skipped embed: no EMBEDDING_API_KEY (or GEMINI_API_KEY) in .env (needed only for modes M2 and M2S)"; fi

# Admin area login. Not built yet.
admin-user: _need-code ## Create an admin user (prompts for details)
	@$(ENV) $(BIN)/storyquest admin create-user

# Runs the stages that need no LLM, in order, printing one line each: verify the file hash,
# clean off Gutenberg's header/footer, find chapters from the Contents list and label story vs
# poem, optionally load hand-written beats (--spine), cut each beat into paragraph chunks, and
# store it all in content.db. Re-running rebuilds chunks and keeps beats unless --spine is given.
ingest: _need-code _need-book ## Run ingestion stages: make ingest BOOK=<id> [ARGS="--spine eval/spine_mowgli_brothers.json"]
	@$(ENV) $(BIN)/storyquest ingest $(BOOK) $(ARGS)

# Runs the model-based ingestion stages after the deterministic ones: 5 cut each story chapter
# into beats (the model proposes where scenes start, code decides), 6 write each beat's title,
# narration, clues, vocabulary and choice (checked by stage 7 and retried), 8 build entity cards.
# Hand-written and approved beats are kept. Each finished step is recorded, so running it again
# resumes after a failure. ARGS: --chapter N, --dry-run (preview the beat boundaries), --force,
# --stage segment|generate|validate|entities, --enqueue (leave it for `make worker`).
# Then `make review`, `make approve`, `make publish`, and `make embed` for hybrid search.
ingest-llm: _need-code _need-book ## LLM stages 5-8: make ingest-llm BOOK=<id> [ARGS="--chapter 2 --dry-run"]
	@$(ENV) $(BIN)/storyquest ingest $(BOOK) --stage llm $(ARGS)

# Which steps finished for a book (with the pipeline version), beats per chapter with how many
# are approved or flagged, recent worker jobs and the entity count.
ingest-status: _need-code _need-book ## Show ingestion steps, beats and jobs: make ingest-status BOOK=<id>
	@$(ENV) $(BIN)/storyquest ingest-status $(BOOK)

# Prints every beat of the book (or --chapter N) as a reviewer reads it: title, narration, clues
# with the source words behind each, vocabulary, the choice, and any validation flags. Flagged
# beats come first.
review: _need-code _need-book ## Read generated beats: make review BOOK=<id> [ARGS="--chapter 2"]
	@$(ENV) $(BIN)/storyquest review $(BOOK) $(ARGS)

# Approves generated draft beats that have no flags. Flagged beats are left until you approve
# them on purpose: ARGS="--beat N" (one beat, zero-based) or ARGS="--flagged" (all in the scope).
approve: _need-code _need-book ## Approve beats: make approve BOOK=<id> [ARGS="--chapter 2 [--beat N | --flagged]"]
	@$(ENV) $(BIN)/storyquest approve $(BOOK) $(ARGS)

# Marks the book ready when every story chapter has approved beats and chunks; otherwise lists
# what is missing.
publish: _need-code _need-book ## Publish a fully approved book: make publish BOOK=<id>
	@$(ENV) $(BIN)/storyquest publish $(BOOK)

# Lists the entity cards (characters, places, terms) with the line where each first appears.
entities: _need-code _need-book ## List entity cards: make entities BOOK=<id>
	@$(ENV) $(BIN)/storyquest entities $(BOOK)

# Processes queued ingestion jobs (`make ingest BOOK=.. ARGS="--stage llm --enqueue"`), one at a
# time, and waits for more; ARGS="--once" stops when the queue is empty.
worker: _need-code ## Run queued ingestion jobs: make worker [ARGS="--once"]
	@$(ENV) $(BIN)/storyquest worker $(ARGS)

# Computes a meaning vector (embedding) for every chunk that lacks one with the configured
# embedding model (EMBEDDING_PROVIDER in config.env), and stores it in content.db (table
# chunk_embeddings, one set per model). Needed once per book and model, and again after `make
# ingest` rebuilds chunks, before using hybrid mode M2 or M2S. Needs the embedding key in .env.
embed: _need-code _need-book ## Embed a book's chunks for hybrid search: make embed BOOK=<id>
	@$(ENV) $(BIN)/storyquest embed $(BOOK) $(ARGS)

# Read-only report from content.db: every chapter with its story/poem label, raw line range and
# beat and chunk counts. With --chapter N it also lists that chapter's beats and chunks.
inspect: _need-code _need-book ## Show chapters, beats, chunks: make inspect BOOK=<id> [ARGS="--chapter 0"]
	@$(ENV) $(BIN)/storyquest inspect $(BOOK) $(ARGS)

# Runs the search the agent will use, as a child standing at --chapter/--beat (zero-based; the
# defaults mean the end of the book). Turns the question into word terms, ranks chunks with BM25,
# and leaves out chunks after the child's position, so spoilers never appear. Add ARGS="--hybrid"
# to also rank by meaning (embeddings) and fuse the two rankings (needs `make embed` first).
search: _need-code _need-book ## Search as a child: make search BOOK=<id> Q="..." [ARGS="--chapter 0 --beat 1"]
	@test -n "$(Q)" || { echo "usage: make search BOOK=<id> Q=\"...\" [ARGS=\"--chapter N --beat N\"]"; exit 1; }
	@$(ENV) $(BIN)/storyquest search $(BOOK) "$(Q)" $(ARGS)

# Asks the story agent one question as a child standing at --chapter/--beat (zero-based), in mode
# MODE (M0 = plain model, M1 = with retrieved book passages, M1S = M1 plus chosen evidence sentences, M2 / M2S = M1 / M1S with hybrid search). Sorts the message with a small
# model call, then (for story questions) retrieves passages up to the child's position, builds the
# prompt, calls the model and checks the reply. Prints the answer and what happened at each step;
# add --verbose to ARGS to see the exact prompts, --no-cache to force fresh model calls.
ask: _need-code _need-book ## Ask the agent: make ask BOOK=<id> Q="..." MODE=M1 [ARGS="--chapter 0 --beat 1 --verbose"]
	@test -n "$(Q)" || { echo "usage: make ask BOOK=<id> Q=\"...\" [MODE=M0|M1] [ARGS=\"--chapter N --beat N\"]"; exit 1; }
	@$(ENV) $(BIN)/storyquest ask $(BOOK) "$(Q)" --mode $(MODE) $(ARGS)

# Opens the sqlite3 command-line shell on content.db or app.db for ad hoc SQL.
db-shell: ## Open sqlite3 on a local database: make db-shell DB=content|app
	@$(ENV) sqlite3 "$${DATA_DIR:-var}/$(DB).db"

# Starts Datasette, a read-only web page for browsing the tables and running SELECT queries.
# Opens whichever of content.db and app.db exist in DATA_DIR (or DATA=<dir>).
db-viewer: ## Browse local databases in Datasette (DATA=dir to point at a snapshot)
	@$(ENV) d="$(DATA)"; d="$${d:-$$DATA_DIR}"; files=""; \
	  test -x $(BIN)/datasette || { echo "datasette not installed: run make setup"; exit 1; }; \
	  for f in content app; do [ -f "$$d/$$f.db" ] && files="$$files $$d/$$f.db"; done; \
	  [ -n "$$files" ] || { echo "No databases in $$d yet: run make seed first"; exit 1; }; \
	  echo "Viewer: http://localhost:$(VIEWER_PORT)  (Ctrl-C to stop)"; \
	  $(BIN)/datasette serve $$files --port $(VIEWER_PORT)

# Asks for confirmation, then deletes content.db and app.db. Uploaded books and the LLM cache
# stay; re-create the data with `make seed` and `make ingest`.
db-reset: ## DELETE the local databases (asks first); books and LLM cache are kept
	@$(ENV) read -p "Delete $$DATA_DIR/content.db and app.db? [y/N] " a; \
	  [ "$$a" = y ] && rm -f "$$DATA_DIR"/content.db* "$$DATA_DIR"/app.db* && echo "Deleted." || echo "Cancelled."

##@ Evaluation

# Runs the golden set through each mode in MODES, one question at a time. Scores every reply
# (behaviour, forbidden words, required facts via an LLM judge, whether the search found the
# answer passage), then writes ONE report.html that explains the modes, compares them, and shows
# every question with the reply, the retrieved passages and why it passed or failed, and opens
# it in the browser. Everything is saved under eval/runs/<time>/ (one folder per mode plus the
# report). Items that need a full quest session are skipped. Model answers are cached, so
# repeat runs are fast. Modes: M0 plain model, M1 retrieval, M1S sentence evidence, M2 hybrid retrieval, M2S hybrid +
# sentence evidence (M2 and M2S need `make embed` first), M3 / M3S = M2 / M2S plus entity cards
# (also need `make ingest-llm`).
# Add ARGS="--no-judge" for a faster run without the judge, ARGS="--no-open" to not open the
# browser, ARGS="--category SPO --limit 5" for a subset.
eval: _need-code ## Run the evals and open the report: make eval [MODES="M0 M1S M2S"] [SPLIT=dev] [ARGS="..."]
	@$(ENV) $(BIN)/storyquest eval run --modes "$(MODES)" --split $(SPLIT) $(ARGS)

# Retrieval on its own, in seconds and with no chat-model calls: for each golden question with a
# gold passage, does keyword, meaning or hybrid search put it in the top k? Uses the configured
# embedding model (run `make embed` for it first). Use it for chunking and embedding experiments,
# e.g. `EMBEDDING_CONTEXT_CHARS=1200 make eval-retrieval` after embedding with the same setting.
eval-retrieval: _need-code ## Recall@k of keyword/meaning/hybrid search: make eval-retrieval [SPLIT=dev] [ARGS="--k 3,6,10"]
	@$(ENV) $(BIN)/storyquest eval retrieval --split $(SPLIT) $(ARGS)

# Rebuilds report.html from a saved folder under eval/runs/ and opens it again, without any
# model calls. Useful after the report layout changes or to look at an old run.
eval-report: _need-code ## Reopen a saved report: make eval-report RUN=eval/runs/<time>
	@test -n "$(RUN)" || { echo "usage: make eval-report RUN=eval/runs/<time>  (see: ls eval/runs)"; exit 1; }
	@$(ENV) $(BIN)/storyquest eval report $(RUN) $(ARGS)

##@ Remote server (SSH alias in REMOTE, default "miles")

# Builds the image for the server's CPU type, streams it over SSH into the server's Docker,
# copies the compose and config files (never .env), then starts the stack there. Not built yet.
deploy: _need-compose ## Build the image, ship it over SSH and restart the stack
	DOCKER_DEFAULT_PLATFORM=$(DEPLOY_PLATFORM) $(COMPOSE) build
	docker save $(IMAGE) | gzip | ssh $(REMOTE) 'gunzip | docker load'
	ssh $(REMOTE) 'mkdir -p $(REMOTE_DIR)'
	rsync -az --relative docker-compose.yml config.env config.prod.env $$(test -d certs && echo certs) $(REMOTE):$(REMOTE_DIR)/
	ssh $(REMOTE) 'cd $(REMOTE_DIR) && test -f .env || { echo "Create $(REMOTE_DIR)/.env with the secrets first"; exit 1; }; docker compose up -d'

# The remote-* targets run commands on the server over SSH (alias in REMOTE). Not built yet.
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

# Deletes Python caches and build output; nothing you would want to keep.
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
