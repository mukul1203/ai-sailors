# 08 — Deployment and Development Environment

Scope: running the app locally with one command, deploying it with Docker to the miles web server, secrets, backups and viewing the databases. Commands below are proposals until the code exists.

## Principles

- Same container image locally and on the server; only configuration differs.
- Local development uses the real model endpoint; a `fake` provider exists for tests and offline work.
- Secrets live only in `.env` and never go into git or the image. Everything else is committed configuration.

## Containers

| Service | Role |
|---|---|
| `app` | API plus the built React files, serving parents, children and admins |
| `worker` | Runs ingestion jobs from the `ingestion_jobs` table (same image, different command) |
| `dbviewer` | Read-only Datasette over the SQLite files, bound to localhost only (admin profile) |

All three share one volume mounted at `/data`, holding `content.db`, `app.db`, uploaded books and the LLM disk cache. On the server it is a bind mount of `<deploy dir>/var`, so backups and snapshots are plain files on the host. SQLite in WAL mode handles one writer at a time, which fits a single host. The job table acts as the queue, so no separate queue service is needed.

The image is multi-stage: build the React app, then a slim Python image with the built static files. It runs as a non-root user.

## Configuration

Two kinds of files, strictly separated.

**Secrets: `.env` (git-ignored).** Only secret values. `.env.example` is committed and lists the names with empty values.

| Variable | Purpose |
|---|---|
| `LLM_API_KEY` | Group model key |
| `LLM_BASE_URL` | Model endpoint URL (IP and port), treated as a secret |
| `SESSION_SECRET` | Signing secret for sessions |

The CA certificate is also kept out of git: put it at `certs/ca.crt` (git-ignored) on each developer machine, and copy it to the server's `certs/` once. It is mounted read-only into the container. `make deploy` syncs `certs/` from your machine if the folder exists.

**Configuration: `config.env` (committed).** Non-secret settings, safe to read in git.

| Variable | Purpose |
|---|---|
| `LLM_PROVIDER` | `openai_compatible` (default) or `fake` |
| `LLM_MODEL` | `Qwen/Qwen3-8B` |
| `LLM_CA_CERT_PATH` | Path to the CA certificate (`certs/ca.crt`); TLS verification stays on |
| `LLM_MAX_CONCURRENCY` | `1` |
| `LLM_REQUESTS_PER_MINUTE` | `50` (endpoint cap is 60) |
| `LLM_TIMEOUT_SECONDS` | `120`; how long one model call may take |
| `CHUNK_TARGET_CHARS` | `1200`; ingestion aims for chunks about this long |
| `CHUNK_MAX_CHARS` | `1800`; a paragraph longer than this is split on sentences |
| `SHORT_CHAPTER_CHARS` | `8000`; chapters shorter than this are labelled poems |
| `DATA_DIR` | `var` locally (git-ignored), `/data` in containers |
| `DBVIEWER_PORT` | Port for the DB viewer |

Per-environment differences go into a small committed override file, for example `config.prod.env` for the server (paths inside the container, for instance). Compose loads them in order: `config.env`, then the override for that environment, then `.env`. A later file wins, and secrets always come from `.env`.

## Running locally

Two ways, both proposed:

1. Containers: `docker compose up` starts `app` and `worker` using the real model endpoint from `config.env` and your key from `.env`. Add `--profile admin` for the DB viewer.
2. Without Docker: run the API and worker with the Python tooling, and the React dev server with hot reload.

Seeding: `storyquest catalog import eval/books` loads the Jungle Book fixture. `storyquest admin create-user` creates a local admin.

### The `fake` provider

Optional. Returns canned or recorded responses, for unit tests, CI, offline work, or when you do not want to use the shared key. Select it with `LLM_PROVIDER=fake` in a local override. Recorded responses can be refreshed deliberately.

### Sharing the model key

The group key allows one active request across everyone, and 60 requests per minute. A request that arrives while another is running gets a 429. Practical rules:

- Local development runs against the real endpoint; the disk cache avoids repeating identical calls.
- Tell the team before starting a long job such as ingestion or an eval run.
- The model layer queues calls, and retries 429 and 503 with increasing delays, stopping after the limit (see doc 05).

## Deploying to the miles web server

- Access is SSH as `root` to host `miles web` (from your SSH config). Prefer creating a non-root deploy user for running Docker; if root is used, still run the containers as a non-root user inside.
- Deploy flow: build the image, push it to a registry or copy it to the host, then `docker compose up -d` there with the server's own `.env` and `/data` volume.
- A reverse proxy in front (for example Caddy or Nginx) handles HTTPS. Automatic certificates need a domain name; with only an IP, you would need a self-signed certificate. This needs a decision.
- Use the compose `restart: unless-stopped` policy and a health endpoint (`/healthz`).
- Log to stdout; read with `docker compose logs`.

## Viewing the databases

SQLite has equivalents to Postgres tools. Recommended: **Datasette**, a web UI to browse tables, run read-only SQL, filter and export. It opens databases read-only.

The viewer is the same service in both places; you choose which database it points at.

**Local database.** `docker compose --profile admin up` runs the viewer over your local `var/` folder, or `make db-viewer` runs it directly.

**Remote database (the miles web server).** The `dbviewer` service runs on the server over `/data/content.db` and `/data/app.db`, published only on the server's `127.0.0.1`. From your laptop, open an SSH tunnel to it using your `miles web` SSH entry, forwarding a local port to the viewer port, then browse `http://localhost:<port>`. You see live remote data, including user data and chat turns. No columns are masked for the prototype.

The viewer is never exposed directly to the internet. An unauthenticated database browser on a public port would let anyone read and query everything, so the tunnel (SSH authentication) is the access control. If tunnelling becomes annoying, the viewer can instead be proxied behind the app's admin login.

**Snapshot copy (optional).** For offline analysis, a helper such as `storyquest db pull` runs SQLite's online backup on the server, copies the result to your machine, and you open it in the local viewer. Do not `scp` a live WAL database directly; the copy can be inconsistent.

Alternatives: `sqlite-web` allows editing, which is risky on server data, so use it locally only. Also `sqlite3 /data/content.db` inside the container for ad hoc queries.

Datasette's exact read-only behaviour and options should be confirmed when we set it up.

## Backups

- The `/data` volume is the only state. Back up `app.db` and uploaded books regularly; `content.db` is rebuildable from the books but costly in model calls, so back it up too.
- Use SQLite's online backup (`.backup`) or `VACUUM INTO`, not a raw file copy of a live WAL database.
- Before the first real parent signs up, test a restore.

## Makefile

The [Makefile](../../Makefile) is the single entry point for developer tasks; `make help` lists everything. It loads `config.env` then `.env` into each recipe's shell, so tasks see both settings and secrets.

| Area | Targets |
|---|---|
| Getting started | `help`, `setup`, `doctor`, `llm-ping` |
| Run | `dev`, `dev-api`, `dev-worker`, `dev-web`, `up`, `down`, `logs`, `ps`, `build` |
| Quality | `check-data`, `test`, `lint`, `format`, `typecheck`, `check` |
| Data and ingestion | `migrate`, `seed`, `admin-user`, `ingest BOOK=`, `inspect BOOK=`, `db-shell DB=`, `db-viewer DATA=`, `db-reset` |
| Evaluation | `eval MODES= SPLIT=`, `eval-report RUN=` |
| Remote (SSH alias `REMOTE`) | `deploy`, `remote-ps`, `remote-logs`, `remote-restart`, `remote-shell`, `remote-viewer`, `remote-db-tunnel`, `remote-db-pull` |
| Cleanup | `clean`, `clean-all` |

Notes:

- Targets for code that does not exist yet (`src/storyquest`, `web/`, `docker-compose.yml`) fail with a clear "not available yet" message. `help`, `doctor`, `llm-ping` and `check-data` work today.
- `deploy` builds for `linux/amd64` (variable `DEPLOY_PLATFORM`; confirm the server's architecture), ships the image over SSH, syncs compose and config files, and restarts. It never uploads `.env`; create that once on the server by hand.
- In the SSH config, `Host miles web` defines two aliases, `miles` and `web`. The Makefile uses `miles`; override with `REMOTE=web`.
- `db-reset` asks for confirmation and deletes only the local SQLite files.
- The Python tooling (`ruff`, `mypy`, `pytest`, `uvicorn`, `datasette`) and the module path `storyquest.api.main:app` are assumptions to adjust when the code exists.

## Operations checklist (MVP)

- [ ] `config.env` and the production override committed; `.env.example` lists secret names only; `.env` ignored
- [ ] CA certificate in `certs/ca.crt` (git-ignored) locally and on the server
- [ ] Admin user created by CLI
- [ ] `/healthz` and log access working
- [ ] DB viewer reachable through the SSH tunnel only, against both local and remote databases
- [ ] Backup and restore tested

## Open questions

- Domain name for the miles web server and who manages DNS.
- Image registry, or copy images by SSH.
- Whether the deployed app gets its own model key.
