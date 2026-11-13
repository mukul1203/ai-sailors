# 03 — Data Stores (SQLite)

Scope: schemas and ownership of the two databases. Everything runs on one server.

## Two database files

| File | Written by | Contents | Lifecycle |
|---|---|---|---|
| `content.db` | Ingestion | Books, chapters, beats, chunks, FTS index, entities | Rebuildable from the catalog; shared by all families |
| `app.db` | Web app | Parents, children, approvals, progress, sessions, turns, badges | Precious; back it up |

Both use WAL mode. All access goes through repository interfaces, so a later move to Postgres touches one layer.

## `content.db`

| Table | Key columns |
|---|---|
| `books` | `id` (Gutenberg id), `title`, `author`, `language`, `age_band`, `summary`, `content_notes`, `visibility`, `status`, `raw_path`, `content_sha256`, `uploaded_by`, `pipeline_version` |
| `ingestion_jobs` | `id`, `book_id`, `options` (json: stages, chapter, force, spine), `status` (`queued`, `running`, `done`, `failed`), `message`, `created_at`, `started_at`, `finished_at` |
| `ingestion_steps` | key `(book_id, chapter_idx, step)` (chapter -1 for the whole book), `pipeline_version`, `input_hash`, `status` (`done` or `failed`), `detail`, `updated_at` |
| `chapters` | key `(book_id, idx)`, `title`, `kind`, `included`, `start_char`, `end_char` |
| `beats` | key `(book_id, chapter_idx, idx)`, `title`, `narration`, `clues` (json) with `clue_quotes` (json, the source words behind each clue), `vocabulary` (json), `choice` (json), `spoiler_reveals` (json), `start_char`, `end_char`, `review_status` (`draft` or `approved`), `source` (`spine` or `llm`), `flags` (json, validation problems), `pipeline_version` |
| `chunks` | `id`, `book_id`, `chapter_idx`, `beat_idx`, `idx`, `text`, `start_char`, `end_char` |
| `chunks_fts` | FTS5 external-content table over `chunks.text` (porter stemming, BM25), kept in sync by triggers |
| `chunk_embeddings` | `chunk_id`, `model_id`, `dim`, `vector` (float32 blob, unit length), one row per chunk and embedding model; deleted with the chunk. Searched with a plain cosine over the visible chunks, which is fast at book scale, so no vector extension is needed |
| `entities` | key `(book_id, key)` (lowercase name), `name`, `kind` (`character`, `place`, `term`), `aliases` (json), `card`, `first_char` (where the name first appears in the text), `card_chapter` and `card_beat` (the passage the card was written from) |

Notes:

- Positions are character offsets into the cleaned text, with chapter index and beat index for cheap filtering.
- Vectors store the embedder ID and dimension. Switching embedder means a new set of vectors, not a migration.
- Published beats are never edited in place: a published book refuses the LLM stages unless forced, and approved beats are kept by every rerun. Beats carry the `pipeline_version` that wrote them, but old and new versions are not stored side by side yet: a forced rebuild replaces the beats.
- Built: `books`, `chapters`, `beats`, `chunks` and `chunks_fts` (migration `0001_init.sql`), `names` (`0002_names.sql`: proper names with the offset where each first appears), `chunk_embeddings` (`0003_embeddings.sql`), and the LLM-stage tables and beat columns above (`0004_llm_stages.sql`). Replacing a book's chapters also removes its beats, chunks, entities and steps (cascade or explicit delete).

## `app.db`

| Table | Key columns |
|---|---|
| `parents` | `id`, `email`, `role` (`parent` or `admin`), auth fields (owned by the auth library) |
| `children` | `id`, `parent_id`, `nickname`, `age_band`, `avatar` (no other personal data) |
| `family_books` | `parent_id`, `book_id`, `approved_at`, `session_cap_minutes` |
| `progress` | `child_id`, `book_id`, `chapter_idx`, `beat_idx`, `pipeline_version`, `state` (json), `updated_at` |
| `sessions` | `id`, `child_id`, `started_at`, `ended_at`, `token_budget`, `time_cap` |
| `turns` | `id`, `session_id`, `role`, `text`, `agent_mode`, `trace_id`, `created_at` |
| `badges` | `child_id`, `book_id`, `badge`, `earned_at` |

Notes:

- Built so far (migration `app/0001_play.sql`): anonymous play sessions only. `sessions` has `id` (a random token), `book_id`, `chapter_idx`, `beat_idx`, `status` (`active` or `completed`), `mode`, `questions`, `created_at`, `updated_at`; `session_events` has the choices and questions of a session (`kind`, `beat_idx`, `text`, `reply`, `route`, `flags`). There are no accounts yet, so the tables above are still to come, and this `sessions` table will then link to a child. `storyquest purge-sessions --days N` deletes sessions not used for N days, with their events: child text is kept only as long as the retention you choose.
- Progress is autosaved server-side on every turn; the client is never trusted for position.
- `progress.pipeline_version` pins the child to the beat version they started with.
- `turns` holds child text and must follow a retention policy (see overview open questions).

## Spoiler filter (the core query)

A child at (chapter `c`, beat `b`) in a book may retrieve:

- chunks from chapters with `idx < c`, and
- chunks in chapter `c` whose beat `idx <= b`.

Because chunks never cross beat boundaries, this is exact. It is applied inside the retrieval query, never after.

## Search

- Phase 1: SQLite FTS5 BM25 over `chunks_fts`, filtered by the rule above.
- Built: dense retrieval over `chunk_embeddings` with the same filter, and hybrid fusion by reciprocal rank fusion (modes M2 and M2S). `make embed BOOK=<id>` computes the vectors; `make ingest` removes them with the chunks, so embed again afterwards.

## Inspecting the databases

Developers browse both files with a read-only web viewer. See [08-deployment-and-dev-environment.md](08-deployment-and-dev-environment.md).

## Migrations

One numbered SQL file per change, applied at startup, tracked in a `schema_migrations` table.

## Open questions

- Retention period for `turns`.
- Auth library choice, which decides the `parents` table shape.
