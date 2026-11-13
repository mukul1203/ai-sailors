# 01 — Book Catalog and Storage

Scope: how curated books are uploaded, stored, described and listed to parents. Ingestion (turning a book into beats and chunks) is a separate doc: [02-ingestion-pipeline.md](02-ingestion-pipeline.md).

## Goals

- Only curated books can be chosen by a parent (allowlist).
- Adding a book means an admin uploads it in the admin view; the parent UI picks it up with no code change.
- Raw source text is stored once, with a hash, so ingestion is reproducible.

## Where files live

Books are not kept in git. Developers upload them through the admin view (see [06-web-app-and-api.md](06-web-app-and-api.md)), and they live on the server's data volume:

```
/data/
  books/
    <gutenberg_id>/
      raw.txt                     Gutenberg plain text, unmodified
      cover.jpg                   optional
  content.db                      book records and everything derived from them
```

The `books` table is the registry (metadata, status, path and hash of the file). Raw files stay unmodified; cleaning happens in ingestion and never rewrites them. Back up the volume, since uploads are not reproducible from git.

The volume path is behind a `BookStore` interface, so it can move to object storage later without touching anything else.

**Exception: the golden-set book.** The Jungle Book text is committed under `eval/books/` because the golden set cites its line numbers and must run against a byte-identical file. Ingestion verifies its hash. Local development and tests seed from `eval/books/`.

## Book record (the `books` table, edited in the admin view)

| Field | Meaning |
|---|---|
| `gutenberg_id` | Project Gutenberg ID, used as the book ID |
| `title`, `author`, `language` | Display and filtering |
| `summary` | Short parent-facing blurb (human-written or reviewed) |
| `age_band` | e.g. `6-9`; set by the curator |
| `visibility` | `listed` or `hidden` (hidden books are skipped by the UI) |
| `content_notes` | Free text for dated or sensitive material the parent should know |
| `source_url` | Where the file was fetched from |
| `sha256` | Hash of the uploaded file, computed on upload |
| `chapters_override` | Optional hand-written chapter boundaries when auto-detection fails |
| `uploaded_by`, `added_on` | Which admin added it, and when |

## Adding a book

1. Download the plain-text file from Project Gutenberg by hand (this respects their robot policy; the app never scrapes).
2. An admin signs in to the admin view and uploads the file with the metadata form (title, author, age band, summary, content notes).
3. The server validates it (text, size limit, Gutenberg markers present), stores it, computes the hash and creates a `books` row with status `allowlisted`.
4. The parent UI lists books from the DB, so the new book appears automatically once it is `ready`.
5. The admin triggers ingestion from the admin view (or the CLI, which calls the same function). See doc 02.

**Dropping in a book (local development).** Put a folder in `books/` (any name, for example `books/11-alice/`) with `raw.txt` (the Project Gutenberg plain-text file, UTF-8, header and footer included) and `book.yaml` with `gutenberg_id`, `title` and `author`; `summary`, `content_notes`, `age_band`, `visibility` and `sha256` (checked if present) are optional. The library (`GET /api/library`, the web page) imports new folders itself, runs the model-free ingestion stages and shows the chapters at once; a folder that cannot be read is listed with the reason and does not hide the others. Choosing a chapter prepares it (see doc 02 and doc 06). `storyquest catalog import <dir>` does the same for a whole folder from the CLI. The `eval/books/` folder holds the Jungle Book fixture.

For local development and tests, `storyquest catalog import <dir>` seeds books from a folder such as `eval/books/`. Each book folder holds `raw.txt` and a `book.yaml` with the same fields as the book record below (the Jungle Book fixture shows the format).

## Statuses

`allowlisted` → `ingesting` → `ready` (or `failed`). Only `ready` books can be started by a child. Parents see all `listed` books with their status.

## Rules

- The catalog never contains a book the curator did not review.
- Replacing the file changes the hash and invalidates existing ingestion output; the book is re-ingested under a new pipeline version rather than edited in place.
- Only admins can upload; parents and children never can.
- Copyright: public-domain in the US only (check Gutenberg's flag); record it in `content_notes` if unsure.

## Open questions

- Who curates and reviews age band and content notes?
- Backup plan for the data volume on the server.
