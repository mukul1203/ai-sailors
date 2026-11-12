# 02 — Ingestion Pipeline (offline)

Scope: turning a catalog book's raw text into chapters, beats, entity cards and searchable chunks. Runs once per book and pipeline version, shared by all families.

## Goals

- Deterministic where possible, LLM where needed, with every LLM output validated against the source text.
- Resumable and idempotent: a crash or retry never duplicates or corrupts data.
- Runnable from a CLI first for debugging; the web app later calls the same function.

## Stages

| # | Stage | How | Output | Status |
|---|---|---|---|---|
| 1 | Verify | Check the stored file's hash against `books.content_sha256` | pass or fail | built |
| 2 | Clean | Keep text between the Gutenberg `*** START` and `*** END` markers; normalise quotes and whitespace; keep a map to original offsets | cleaned text | built |
| 3 | Detect chapters | Use the Contents list and heading matches; fall back to `chapters_override` on the book record | `chapters` rows with start and end offsets | built (no override yet) |
| 4 | Classify chapters | `story`, `poem`, `front`, `back`; only `story` chapters become missions | `kind`, `included` | built (`story` and `poem`) |
| 5 | Segment beats | LLM proposes paragraph boundaries; code validates that beats form a contiguous partition of the chapter | beat spans | built |
| 6 | Generate beats | LLM, JSON-schema output, per beat: narration, clues, vocabulary, choice cards, spoiler reveals | `beats` rows (draft) | built |
| 7 | Validate beats | Quotes must appear verbatim in the span; length and reading-level checks; safety screen | pass, flag or retry | built |
| 8 | Entity cards | Extract characters and terms with aliases, a short child-friendly card and a `first_appears` position | `entities` rows | built |
| 9 | Chunk and index | Paragraph-group chunks that never cross a beat boundary; BM25 index; vectors are added afterwards by `make embed` | `chunks`, FTS index | built |
| 10 | Review | A human approves beats for new books (flagged ones first) | beats `approved` | built (CLI) |
| 11 | Publish | Mark the book `ready` | `books.status = ready` | built (CLI) |

Stage 1 to 4 and 9 need no model. Chapter 1 of the Jungle Book keeps its hand-written beats (the spine), which start approved and are never overwritten without `--force`; they are also the yardstick for stage 5.

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

## The LLM stages as built

**Stage 5, segment.** A chapter does not fit in one call, so the model sees `SEGMENT_WINDOW_PARAGRAPHS` numbered paragraph openings (the first 160 characters and a word count) at a time and answers `{"starts": [paragraph numbers]}` for where a new scene begins. Code keeps only valid numbers, then picks the subset of proposed boundaries whose beats are closest to `BEAT_TARGET_CHARS` with every beat between `BEAT_MIN_CHARS` and `BEAT_MAX_CHARS` (a small dynamic program). If no subset fits, it merges too-small beats and splits too-large ones at the paragraph nearest the middle. A chapter shorter than the maximum is one beat and needs no call. An unreadable answer is ignored, so the worst case is a chapter cut by size alone. Measured on chapter 1 against the hand-written spine: 4 of 4 spine boundaries have a generated boundary within 1,500 characters (two exact), with two extra beats.

**Stage 6, generate.** One call per beat, with the scene text (never more than 12,000 characters) and a short peek at the next scene so the model can mark which choice option matches the book. The JSON has title, narration summary, 3 to 5 clues (each with a `quote` copied from the scene and a short `clue`), vocabulary, a choice question and 2 or 3 options with the canon one. `spoiler_reveals` is not generated: it is filled by code from the titles and clues of later beats and the titles of later chapters.

**Stage 7, validate.** Code only. Each clue quote must be a stretch of the scene (case, spacing and curly quotes ignored), vocabulary must occur in the scene, the title and narration have length limits, the choice needs a question and 2 or 3 options with one marked canon, the narration is checked against a provisional reading grade (Flesch-Kincaid at most 8), and a short word list screens the generated text. Problems that asking again can fix (quotes, vocabulary, lengths, safety words, unreadable JSON) trigger up to `INGEST_RETRIES` retries with the problems listed in the prompt. After that, untraceable clues and vocabulary are dropped (so stored clues are always backed by the book) and what is still wrong is stored as readable `flags` on the beat. The screen is minimal and screens only the generated text; the reviewer is the real check.

**Stage 8, entities.** One call per beat lists the named characters, places and terms in it. Code keeps an entity only if its name occurs in the book text, takes `first_char` from the text (never from the model), merges repeats and aliases across beats, and keeps the card from the first beat that mentioned it, so a card cannot describe later events. Modes M3 and M3S use the cards (doc 04, doc 10).

**Stages 10 and 11.** `make review` prints each beat with its clues next to the source words and its flags (flagged beats first). `make approve` approves clean drafts; flagged ones need `--beat N` or `--flagged`, a deliberate act. `make publish` marks the book `ready` only if every story chapter has approved beats and chunks, and otherwise lists what is missing.

## Idempotency and recovery

- Each LLM step is recorded per chapter in `ingestion_steps` with the pipeline version and a hash of its input (the chapter text, beat boundaries and the version). A rerun skips a step whose stored hash matches, so it resumes at the chapter that failed; `--force` redoes steps.
- `pipeline_version` is a short hash of the prompts, the model id, the beat and chunk settings and the safety list, so changing any of them makes old steps stale.
- Hand-written beats and approved beats are never replaced by a normal run. A published (`ready`) book refuses LLM stages without `--force`. Replacing a book's chapters (the chapter list changed) clears its beats, chunks, entities and steps.
- LLM calls are cached on disk by request hash, which also saves token quota on reruns.
- A failed step (the model endpoint was down, say) is recorded as `failed`, the run continues with the next chapter, the book is marked `failed`, and the command exits non-zero.
- `ingestion_jobs` is a simple queue: `--enqueue` adds a job and `make worker` runs queued jobs one at a time. Two workers on one database are not guarded against yet.
- Chunking (stage 9) rebuilds all chunks and with them the embeddings, so run `make embed` afterwards.

## CLI

```
storyquest ingest <book_id> [--stage S] [--chapter K] [--dry-run] [--force] [--enqueue] [--spine FILE]
storyquest ingest-status <book_id>             # steps, beats per chapter, jobs
storyquest inspect <book_id> [--chapter K]     # print chapters, beats, chunk counts
storyquest review <book_id> [--chapter K]      # read generated beats and their flags
storyquest approve <book_id> [--chapter K] [--beat N | --flagged]
storyquest publish <book_id>
storyquest entities <book_id>
storyquest worker [--once]
```

`--stage` is `deterministic` (the default, no model), `llm` or `all` (segment, generate, entities), or one or more of `segment` (5), `generate` (6), `validate` (7, a code-only recheck of stored beats), `entities` (8). `--dry-run` previews beat boundaries and compares them with existing beats without writing anything. The Makefile wraps these: `make ingest`, `make ingest-llm`, `make ingest-status`, `make review`, `make approve`, `make publish`, `make entities`, `make worker`.

The admin view will trigger the same `run_ingestion` by inserting a row into `ingestion_jobs`; the worker picks it up. Progress reporting for the UI is not built.

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
