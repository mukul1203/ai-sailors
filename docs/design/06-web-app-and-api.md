# 06 — Web App and API

Scope: parent and child experience, the HTTP API, auth, progress and job status. The UI lists what the DB holds; it hardcodes no books.

## Roles and flows

**Admin (app developers only)**

1. Sign in to the admin view. Admin accounts are created from the CLI, never through public sign-up.
2. Upload a Gutenberg text file with metadata, review the book list and statuses.
3. Trigger ingestion, watch its progress and approve beats.
4. Open the database viewer (see doc 08).

**Parent**

1. Sign up or log in.
2. Add child profiles (nickname, age band, avatar only).
3. Browse the catalog (`ready` books, with content notes) and approve books for the family.
4. Set the session cap per child.
5. See progress.
6. Later: see books that are still being ingested, with a polled progress bar.

**Child**

1. Pick a profile on a parent-authenticated device (children have no credentials).
2. See missions from approved, `ready` books.
3. Play a mission: beat narration, choice cards, optional free text.
4. Resume where they left off; wrap-up when the session cap is reached.

## API (proposed)

| Endpoint | Purpose |
|---|---|
| auth routes (library-provided) | Parent login and session |
| `GET /catalog` | `ready` books, from `content.db` |
| `POST /family/books/{book_id}` | Approve a ready book for the family |
| `GET/POST /children` | Manage child profiles |
| `GET /children/{id}/missions` | Playable missions with progress |
| `POST /sessions` | Start a session for a child and mission |
| `GET /sessions/{id}/beat` | Current beat for display |
| `POST /sessions/{id}/turn` | A choice click or free text; runs the live agent and returns the reply and next state |
| `GET /children/{id}/progress` | Parent progress view |
| `POST /admin/books` | Admin only: upload a book file and metadata |
| `GET /admin/books` | Admin only: all books with status |
| `POST /admin/books/{id}/ingest` | Admin only: enqueue ingestion |
| `GET /admin/books/{id}/ingestion` | Admin only: job status and per-stage progress (polled) |
| `POST /admin/books/{id}/beats/{beat_id}/approve` | Admin only: approve a reviewed beat |

## Rules

- **Server-owned state:** Position, time cap and token budget live on the server. The client sends a choice ID or text only.
- **Autosave:** Progress is written on every turn, so resume is trivial.
- **Cap enforcement:** The server ends the session at the cap; chat messages cannot change it.
- **Catalog freshness:** `catalog sync` updates the DB; the UI reads it live, so new books show up without a redeploy.
- **Rate limiting and caching:** Per-session turn rate limit; cache catalog and beat reads.

## Status and notifications

No notifications. The UI polls job status endpoints. Streaming is used only for the agent's reply text.

## Security and privacy

- Use a vetted auth library, not hand-rolled auth.
- Store only parent email and child nickname, age band and avatar.
- Redact PII from turns and traces; define a retention period.
- Parent approval is the human-in-the-loop boundary for what a child can access.

## UI technology

React single-page app (parent, child and admin areas), built to static files and served alongside the API. No child PIN: a parent-authenticated device session is enough.

## Open questions

- Auth library for Python plus React sessions.
- Whether session caps and badges are in the MVP (see overview).
