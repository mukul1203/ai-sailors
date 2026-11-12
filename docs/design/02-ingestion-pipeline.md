# 02 — Ingestion Pipeline (offline)

Scope: turning a catalog book's raw text into chapters, beats, entity cards and searchable chunks. Runs once per book and pipeline version, shared by all families.

## Goals

- Deterministic where possible, LLM where needed, with every LLM output validated against the source text.
- Resumable and idempotent: a crash or retry never duplicates or corrupts data.
- Runnable from a CLI first for debugging; the web app later calls the same function.

## Stages

| # | Stage | How | Output |
|---|---|---|---|
| 1 | Verify | Check the stored file's hash against `books.content_sha256` | pass or fail |
| 2 | Clean | Keep text between the Gutenberg `*** START` and `*** END` markers; normalise quotes and whitespace; keep a map to original offsets | cleaned text |
| 3 | Detect chapters | Use the Contents list and heading matches; fall back to `chapters_override` on the book record | `chapters` rows with start and end offsets |
| 4 | Classify chapters | `story`, `poem`, `front`, `back`; only `story` chapters become missions | `kind`, `included` |
| 5 | Segment beats | LLM proposes paragraph boundaries; code validates that beats form a contiguous partition of the chapter | beat spans |
| 6 | Generate beats | LLM, JSON-schema output, per beat: narration, clues, vocabulary, choice cards, spoiler reveals | `beats` rows (draft) |
| 7 | Validate beats | Quotes must appear verbatim in the span; length and reading-level checks; safety screen | pass, flag or retry |
| 8 | Entity cards | Extract characters and terms with aliases, a short child-friendly card and a `first_appears` position | `entities` rows |
| 9 | Chunk and index | Paragraph-group chunks that never cross a beat boundary; BM25 index; vectors are added afterwards by `make embed` | `chunks`, FTS index |
| 10 | Review | A human approves beats for new books (flagged ones first) | beats `approved` |
| 11 | Publish | Mark the book `ready` | `books.status = ready` |

## Key rules

- **Beats partition the chapter.** Each beat covers a contiguous span, together covering the whole playable chapter. This makes the spoiler boundary exact: a child at beat *k* may see only chunks from earlier chapters and from beats up to *k*.
- **Chunks never cross beat boundaries.** Segment beats first, chunk after.
- **Beats start at paragraph starts.** Enforced when beats are loaded; a boundary that falls mid-paragraph is rejected, because it would split a sentence across two beats.
- **Story-vs-poem is a heuristic.** A chapter is a poem if it is short (under 8,000 characters) or made of short indented lines. This is right for the Jungle Book (7 stories, 7 poems) but would mislabel a collection of very short stories, so the labels are reviewed with `make inspect` before a book is published.
- **Position is stored, not inferred.** Every chunk, beat and entity carries chapter index and character offsets into the cleaned text.
- **Endpoint limits shape everything.** The model allows 8,192 tokens combined input and output per call and at most 1,024 output tokens. A Jungle Book chapter is well over 8k tokens on its own (estimate), so no chapter fits in one call.
  - Work in windows of roughly 3–4k source tokens, leaving room for the prompt and output.
  - Segment boundaries in a first pass, then generate one beat per call with a small JSON output, not a whole chapter at once.
  - Merge window boundaries in code, not in the model.
- **Throughput is serial.** The group key allows 1 active request at a time, shared with everyone using it, and 60 requests per minute. A book is many calls, so ingestion is slow and competes with development and live traffic. Use the disk cache and prefer running ingestion when the key is otherwise idle.
- **Faithfulness:** An LLM may rewrite for reading level, but clues and facts must trace to source spans. Any beat whose quotes fail the string check is retried, then flagged for review.
- **Versioning:** Output is keyed by `pipeline_version` (prompts, model id, chunk settings). A new version writes new rows. Published beats are never edited in place, so a child mid-quest keeps a stable story.

## Idempotency and recovery

- Each step has a key `(book_id, pipeline_version, chapter, step)` and an input hash; if both match a completed step, it is skipped.
- LLM calls are cached on disk by request hash, which also saves token quota on reruns.
- Failures are recorded per step (`ingestion_steps`), not per book, so a rerun resumes at the failed chapter.
- Concurrent requests for the same book take a lock: one job runs, others wait on its status.

## CLI

```
storyquest ingest <book_id> [--stage N] [--chapter K] [--dry-run] [--force]
storyquest inspect <book_id> [--chapter K]     # print chapters, beats, chunk counts
storyquest ingest-status <book_id>
```

The admin view triggers the same `run_ingestion(book_id)` by inserting a row into `ingestion_jobs`; a separate worker process picks it up and reports per-stage progress. The UI polls the status.

## Progressive publishing (after the MVP)

The MVP publishes a book only when all chapters are ready. Later, chapters can be published as they finish, with these rules:

- Chapters are ingested and published strictly in order. A failure at chapter *k* blocks *k+1* onward but leaves earlier chapters playable.
- A child can start chapter *k* only after completing chapter *k-1*. Missions unlock in sequence.
- Entity cards and the spoiler filter rely on earlier chapters being present, which the ordering guarantees.
- Status becomes per-chapter, and the book is `ready` once at least one chapter is.

## Validation of the Jungle Book

Chapter 1 beats are already hand-drafted in [eval/spine_mowgli_brothers.json](../../eval/spine_mowgli_brothers.json). They are the gold reference to compare generated beats against.

## Open questions

- Reading-level measure and target for narration.
- Poems and songs in the text: skip, summarise or include as vocabulary?
- How much human review per book is acceptable?
