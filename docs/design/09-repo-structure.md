# 09 — Repository Structure

Scope: where code, data, docs and config live. Items marked **exists** are in the repo today; everything else is proposed and gets created when the component is built. Component behaviour is in docs 01 to 08.

## Top level

```
ai-sailors/
├── Makefile                  exists   developer entry point (doc 08)
├── README.md                 exists
├── LICENSE                   exists
├── .gitignore                exists
├── .env.example              exists   secret names only
├── config.env                exists   non-secret settings, committed
├── config.prod.env                    server overrides, committed
├── pyproject.toml                     Python package, dependencies, tool config
├── Dockerfile                         multi-stage: build web, then slim Python image
├── docker-compose.yml                 app, worker, dbviewer (profile: admin)
├── certs/                             model endpoint CA certificate (public)
├── docs/                     exists
├── eval/                     exists
├── data/spine/               exists   hand-written reference spines
├── fixtures/                          committed sample inputs for tests and the golden set
├── scripts/                  exists   small standalone helpers
├── src/storyquest/                    backend package
├── tests/                             backend tests
├── web/                               React app
├── var/                               local runtime data (git-ignored)
└── runs/                              eval run outputs (git-ignored)
```

## Docs

```
docs/
├── capstone-brief.md         exists
├── mvp-prd.md                exists
├── eval-golden-set.md        exists
└── design/                   exists   one doc per component, 00 is the overview
```

## Eval, data and fixtures

```
eval/
└── golden_v1.jsonl           exists   frozen when v1 is released; later versions are new files
data/
└── spine/
    └── mowgli_brothers.json  exists
fixtures/
└── books/
    └── 236-the-jungle-book/           (ID to verify)
        ├── raw.txt                    moved from jungle_book_plain_text.txt at the repo root
        └── book.yaml                  metadata used by `catalog import`
```

The Jungle Book fixture is the only book in git. All other books are uploaded through the admin view and live in `var/` locally and on the server's data directory.

## Backend: `src/storyquest/`

```
src/storyquest/
├── cli.py                    entry point for the `storyquest` command
├── config.py                 loads config.env and .env into typed settings
├── domain/                   plain data types shared everywhere
│   ├── book.py                 Book, Chapter, Beat, Chunk, Entity
│   ├── position.py             Position (chapter, beat, char offset) and spoiler rules
│   └── session.py              turn input and output, agent state
├── models/                   model layer (doc 05)
│   ├── llm.py                  LLMClient interface and result types
│   ├── openai_compatible.py    Qwen3-8B endpoint client
│   ├── fake.py                 canned or recorded responses for tests
│   ├── queue.py                global request queue, concurrency 1, 429 and 503 retry
│   ├── cache.py                disk cache keyed by request hash
│   ├── embedder.py             Embedder interface (no implementation yet)
│   └── reranker.py             Reranker interface and the LLM listwise version
├── stores/                   databases (doc 03)
│   ├── db.py                   connections, WAL, migration runner
│   ├── migrations/             numbered SQL files, content and app
│   ├── content_repo.py         books, chapters, beats, chunks, entities, jobs
│   ├── app_repo.py             users, children, approvals, progress, sessions, turns
│   ├── search.py               FTS5 BM25 with the spoiler filter
│   └── book_store.py           BookStore interface and the local-volume version
├── catalog/                  upload validation and `catalog import` (doc 01)
├── ingestion/                offline pipeline (doc 02)
│   ├── pipeline.py             runs stages, handles resume and idempotency
│   ├── worker.py               picks up ingestion_jobs
│   ├── stages/                 clean, chapters, segment, beats, validate, entities, chunk, screen
│   └── prompts/                prompt files, versioned with pipeline_version
├── agent/                    live agent (doc 04)
│   ├── turn.py                 orchestrates one child turn
│   ├── modes.py                M0 to M5 feature flags
│   ├── router.py               rules plus the classifier prompt
│   ├── guard.py                input checks and PII scrubbing
│   ├── rewrite.py  retrieve.py  rerank.py  context.py  generate.py
│   ├── output_check.py         non-LLM spoiler and banned-term check
│   ├── critic.py               later
│   ├── tools.py                retrieve_canon, lookup_entity, advance_beat, award_badge
│   └── prompts/
├── api/                      HTTP layer (doc 06)
│   ├── main.py                 app factory, static files, health
│   ├── auth.py  deps.py  schemas.py
│   └── routes/                 catalog, family, children, sessions, admin, health
└── evaluation/               eval harness (doc 07)
    ├── runner.py  checks.py  judge.py  failure_labels.py
    ├── report/                 HTML template and builder
    └── compare.py
```

The eval package is named `evaluation` to avoid shadowing Python's built-in `eval`.

### Dependency rules

```
domain  <-  stores, models  <-  catalog, ingestion, agent  <-  api, cli, evaluation
```

- `domain` imports nothing from the project.
- `stores` and `models` depend only on `domain`.
- `ingestion` and `agent` depend on `stores`, `models` and `domain`, never on each other and never on `api`.
- `api` and `evaluation` call `agent.turn` directly, so the web app and the eval runner share one code path.
- `cli.py` wires everything and holds no logic of its own.
- Route handlers stay thin: validate, call a function in `agent`, `ingestion` or `stores`, return.

## Tests: `tests/`

The layout mirrors `src/storyquest/`, so a module's tests are easy to find.

```
tests/
├── conftest.py               shared fixtures: temp databases, fake LLM, test client
├── domain/
├── models/
├── stores/
├── catalog/
├── ingestion/
├── agent/
├── api/
├── evaluation/
└── data/                     small text samples and recorded model responses
```

- Tests use the `fake` provider and never touch the shared model key.
- Slower tests that use real SQLite files or the API test client carry the `integration` marker.
- Tests that call the real model endpoint carry the `live` marker and are skipped by default; run them on purpose.

## Frontend: `web/`

```
web/
├── package.json  vite.config.ts  tsconfig.json
├── index.html
└── src/
    ├── main.tsx  App.tsx  routes.tsx
    ├── api/                  typed client for the API, one place for fetch and polling
    ├── features/
    │   ├── auth/               login and sign-up
    │   ├── parent/             catalog, child profiles, approvals, progress
    │   ├── child/              mission list, beat view, choice cards, chat box
    │   └── admin/              upload, ingestion status, beat review, DB viewer link
    ├── components/             shared UI pieces
    └── styles/
```

The production build outputs to `web/dist`, which the Docker image copies next to the API.

## Runtime data (not in git)

```
var/                          local; mounted as /data in containers
├── content.db
├── app.db
├── books/<gutenberg_id>/raw.txt
├── cache/                    LLM disk cache
├── backups/
└── remote-snapshot/          from `make remote-db-pull`
```

## Conventions

- One concern per module; no "utils" dumping ground.
- Prompts live in `prompts/` folders as files, not inline strings, so changes are reviewable and tied to `pipeline_version`.
- SQL lives in `stores/migrations/` and the repo classes; nothing else issues SQL.
- Settings come only from `config.py`; no module reads environment variables directly.
- Names in code follow the docs (beat, chunk, position, mode) so docs and code stay searchable together.
- One Python package for everything. `ingestion` and `agent` stay as modules inside it; splitting them later is possible because they do not import each other.
