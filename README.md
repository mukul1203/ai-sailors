# ai-sailors

StoryQuest Copilot: a parent-approved, book-grounded storytelling game for children aged 6 to 9,
built on public-domain Project Gutenberg books with a retrieval-augmented agent. Capstone project
(Track B: hosted Qwen3-8B, no GPU).

What exists today: the ingestion pipeline including the model-based stages and review, keyword and
hybrid (keyword plus meaning) retrieval with a spoiler filter, the agent in several modes, an
evaluation harness with an HTML report, and a playable quest in the browser (an API plus a plain
web page, no accounts yet). The parent and admin areas and deployment are not built yet; their
`make` targets print a clear message.

## Quick start

You need Python 3.11+ and `make`. You also need from the team: the model key and URL with its CA
certificate, and (for hybrid search only) the course's embedding key and URL with its own CA
certificate.

```
make setup        # creates .env, the virtual environment and installs everything

.\.venv\Scripts\python.exe -m pip install -e ".[reranker]"
```

1. Edit `.env` (git-ignored): `LLM_API_KEY`, `LLM_BASE_URL`, and for hybrid search
   `EMBEDDING_API_KEY` and `EMBEDDING_BASE_URL`.
2. Put the model's certificate at `certs/ca.crt` and the embedding endpoint's at
   `certs/vm02-ca.crt` (they are different files). upGrad ships the model's certificate as
   `vm06-ca.crt` (the chat server is VM06): save it as `certs/ca.crt`. The embedding one comes
   as `vm02-ca.crt` (VM02) and keeps its name. The embedding certificate, key and URL come from
   the upGrad email "[IMPORTANT] Capstone Track B – Embedding Model Endpoint (API Access)".
3. Check it all:

```
make doctor       # tools, secrets and certificate: every line should say "ok"
make llm-ping     # one tiny request to the model: "HTTP 200" means it works
make check        # data checks, lint, types and tests (no network needed)

```

4. Load the Jungle Book (seed, ingest with the hand-written beats, embed for hybrid search):

```
make demo-data
```

5. Play with it. Positions are zero-based: `--chapter 0 --beat 4` is the child at the fifth beat.

```
make search BOOK=236 Q="Why did Mowgli cry?" ARGS="--chapter 0 --beat 4 --hybrid"
make ask BOOK=236 Q="Why did Mowgli cry?" MODE=M2S ARGS="--chapter 0 --beat 4"
make ask BOOK=236 Q="Who is Tabaqui?" MODE=M1 ARGS="--chapter 0 --beat 0 --verbose"
make inspect BOOK=236                # chapters, beats and chunks
make db-viewer                       # browse the databases at http://localhost:8001
```

6. Play the game in your browser (children's view): choose what happens next and ask the sidekick
   questions. The model answers the questions, so this needs the model key and certificate.

```
make dev-api                         # then open http://localhost:8000
```

   Only published books with approved beats are listed (see the Books and Review tabs below). Without a model key
   you can still click through the quest; the sidekick just says it is resting.

7. Evaluate and read the report (opens in your browser, takes a while: the model endpoint handles
   one request at a time):

```
make eval                            # M0, M1S and M2S on the dev split
make eval MODES="M1 M1S M2 M2S"      # compare keyword and hybrid retrieval
make eval ARGS="--category SPO --limit 5"   # a quick subset
make eval MODES="M2S M4S" SPLIT=dev ARGS="--no-open"
```

   To check the search alone, in seconds and with no model calls (recall@k of keyword, meaning
   and hybrid search against the golden set's gold passages), use `make eval-retrieval`:

```
make eval-retrieval                  # dev split, k = 3, 6, 8 and 10
make eval-retrieval ARGS="--k 6"     # only the agent's own top-k
```

Everything has a `make` target; `make help` lists them all, and each target has a comment in the
[Makefile](Makefile) explaining what it does.

## Adding your own stories

Put each book in its own folder under **`books/`**:

```
books/
  11-alice/
    raw.txt        the Project Gutenberg plain-text file (UTF-8), header and footer included
    book.yaml      gutenberg_id: 11
                   title: Alice's Adventures in Wonderland
                   author: Lewis Carroll
                   # optional: summary, content_notes, age_band, visibility, sha256
```

Then `make dev-api` and open http://localhost:8000. The page has three tabs (no sign-in yet; they
are meant to be gated later):

- **Books** (grown-ups): add a book with the form (Gutenberg number, title, author and the `.txt`
  file; it is saved as a folder like the one above), or drop a folder in by hand. Each book is a
  folder holding its chapters; choose **Prepare this story** (or **Prepare all**) and the model
  builds them while you wait. The model serves one request at a time, so this takes a few minutes
  per chapter; the line under the chapter shows progress.
- **Review** (grown-ups): pick a book, read each part, the question and its answers, and the
  warnings the checks raised. Approve parts one by one (parts with a warning only one by one), or
  all parts without a warning. When every chapter is prepared and approved, **Publish this book**.
- **Play** (children): the chapters of published books. Publishing also computes the book's
  embeddings once (if the quota runs out, the book is still published; `make embed` finishes it).

A book with a Contents list is split into its chapters; one without is a single story. If a book
cannot be read, the page says why and the other books still work. `BOOKS_DIR` in
[config.env](config.env) lists the folders that are scanned (default `books,eval/books`).

## Ingesting a whole book (model-based stages)

`make demo-data` loads chapter 1 of the Jungle Book with its hand-written beats. The other
chapters get their beats, clues, vocabulary, choices and entity cards from the model, then a human
reviews them:

```
make ingest-llm BOOK=236 ARGS="--chapter 2 --dry-run"   # preview where the beats would start
make ingest-llm BOOK=236                               # all story chapters (slow: one request at a time)
make ingest-status BOOK=236                            # what finished, what is flagged
make review BOOK=236 ARGS="--chapter 2"                # read beats, clues next to their source words
make approve BOOK=236                                  # approve clean drafts (flagged ones need --beat N)
make publish BOOK=236                                  # ready once every chapter is approved
make embed BOOK=236                                    # chunks were rebuilt: embed them again
```

Hand-written and approved beats are never overwritten, finished steps are skipped on a rerun (so
a failure resumes where it stopped), and `--force` redoes things on purpose. Details and the
rules the validation applies: [docs/design/02-ingestion-pipeline.md](docs/design/02-ingestion-pipeline.md).

## Modes

The same agent code runs every mode; only the settings differ.

| Mode | Retrieval | Evidence sentences | Needs the embedding endpoint |
|---|---|---|---|
| M0 | none (plain model) | no | no |
| M1 | keyword (BM25) | no | no |
| M1S | keyword (BM25) | yes: the model picks the numbered sentences it relies on | no |
| M2 | hybrid: keyword plus meaning, fused by reciprocal rank fusion | no | yes |
| M2S | hybrid | yes | yes |
| M3 / M3S | hybrid, plus entity cards for named characters, places and terms | no / yes | yes, and `make ingest-llm` for the cards |
| M5 | **agent loop**: a planner chooses tools (search the book, look up a name, read the scene), then a critic checks the answer; remembers the session's last questions | yes | no: its search uses keywords alone without it |
| M2S-FS / M2S-COT / M2S-DEC, M5-FS / M5-COT | M2S or M5 with a few-shot, chain-of-thought or decomposition answer prompt, for the prompting comparison (`make eval-prompting`) | yes | as M2S / M5 |

M2S is the best mode (72% on the dev split in an earlier run; 66% in the comparison below, on the
same machine and code for every row). M3S, the entity-card variant, scored 68% in its first
run: the card for a name ("Akela is the leader of the wolf pack") can win the model's attention
over the book sentences that hold the exact facts, so M3 and M3S are experimental.

Hybrid modes need `make embed BOOK=<id>`
once per book, and again after `make ingest` rebuilds the chunks (`make demo-data` does both).
If the vectors are missing, hybrid modes fall back to keyword search and the turn carries the flag
`no_vectors`. `make embed` stores each batch as it goes, earliest chapter first, and resumes where
it stopped.

### Embedding models

Vectors are stored per model, so switching models means `make embed BOOK=<id>` once for the new
one (the old vectors stay and are used again if you switch back).

| `EMBEDDING_PROVIDER` | Model | Dimensions | Keys in `.env` |
|---|---|---|---|
| `openai_compatible` (default) | the course endpoint's `bge-small-en-v1.5`, at most 16 texts per request | 384 | `EMBEDDING_API_KEY`, `EMBEDDING_BASE_URL`, certificate at `certs/vm02-ca.crt` |
| `gemini` | `gemini-embedding-001` (free tier: per-minute and daily quotas) | 768 | `GEMINI_API_KEY` |

**Scene context** (`EMBEDDING_CONTEXT_CHARS`, default 1200): each chunk's vector is made from the
chunk plus the end of the chunk before it and the start of the one after, from the same beat only,
up to that many characters. The model still receives the chunk itself; only the search
fingerprint carries the context, and a beat the child has not reached never lends its words.
Vectors are tagged `+ctx1200`, so changing the setting needs `make embed` again. Texts are cut to
`EMBEDDING_MAX_CHARS` (1,600) because the endpoint refuses anything over 512 tokens.

To use Gemini, set the model settings for one command, for example
`EMBEDDING_PROVIDER=gemini EMBEDDING_MODEL=gemini-embedding-001 EMBEDDING_DIM=768 EMBEDDING_CONTEXT_CHARS=0 make eval`.
`EMBEDDING_QUERY_PREFIX` puts an instruction in front of search questions only (BGE models are
trained with one); leave it empty to turn it off.

**Measured on 16 Nov 2026** (dev split, mode M2S, top 6; retrieval from `make eval-retrieval`,
pass rate from `make eval`; 23 questions have a gold passage, 47 facts have evidence lines):

| Embeddings | Gold passage found | Facts' evidence found | M2S pass rate |
|---|---|---|---|
| none (M1S, keyword only) | 15 / 23 | 28 / 47 | 29 / 47 (62%) |
| Gemini `gemini-embedding-001` | 22 / 23 | 45 / 47 | 31 / 47 (66%) |
| `bge-small-en-v1.5`, chunk alone | 18 / 23 | 35 / 47 | 29 / 47 (62%) |
| `bge-small-en-v1.5`, chunk alone + query prefix | 18 / 23 | 35 / 47 | 30 / 47 (64%) |
| **`bge-small-en-v1.5` + scene context (default)** | **20 / 23** | **42 / 47** | **31 / 47 (66%)** |

The small bge model alone finds fewer gold passages than Gemini; scene context closes most of that
gap and the answers match Gemini's pass rate. Tuning the fusion (candidates, `RRF_K`, a heavier
weight on meaning) changed nothing, and the query prefix only reordered the top 3. With
`RETRIEVAL_TOP_K=8` M2S passed 32 / 47 for 19% more prompt tokens; one question is within the
judge's noise, so top-k stays 6. Each pass-rate point is about one question in 47, judged by the
same 8B model, so treat one- or two-question differences as noise.

## Configuration

- Secrets go in `.env` (see [.env.example](.env.example)). It is git-ignored.
- Settings are in [config.env](config.env), with a comment per group: chunk size (500
  characters), passages per turn (`RETRIEVAL_TOP_K`, 6), model and embedding settings.
- Settings you set in your shell win over both files, for example
  `RETRIEVAL_TOP_K=3 make eval MODES=M2S`.
- OpenTelemetry (optional): `make jaeger` starts a local viewer (Docker or Podman), then run
  the app or an eval with `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318` and open
  http://localhost:16686. Each question is one trace with a span per model and tool call; no
  child text is sent unless `OTEL_TRACE_TEXT=true`.
- Runtime data (databases, model and embedding caches, eval runs) lives in `var/` and
  `eval/runs/`, both git-ignored. `make db-reset` deletes the databases; `make demo-data` rebuilds
  them.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `make doctor` says MISSING | add the value to `.env`, or the certificate to `certs/ca.crt` |
| `make ask ... MODE=M2S` says it needs an embedder | set `EMBEDDING_API_KEY` and `EMBEDDING_BASE_URL` in `.env` and the certificate at `certs/vm02-ca.crt`, then `make embed BOOK=236` |
| Hybrid turns carry the flag `no_vectors` after switching embedding models | `make embed BOOK=236` once for the new model |
| Hybrid results look stale after changing chunk size | `make ingest ...` then `make embed BOOK=236` (or `make demo-data`) |
| Model calls are slow or time out | the endpoint serves one request at a time for the whole group; avoid parallel runs |
| Want fresh model answers, not cached | add `--no-cache` to `ARGS` |

## Documents

- [Capstone brief](docs/capstone-brief.md) and [MVP requirements](docs/mvp-prd.md)
- [Design docs](docs/design/00-architecture-overview.md): overview, then one doc per component.
  Most useful for this stage: [live agent](docs/design/04-live-agent.md),
  [eval harness](docs/design/07-eval-harness.md) and
  [scoring reference](docs/design/10-scoring-reference.md) (every threshold that decides a result)
- [Golden eval set and how to run it](eval/README.md); all eval data lives in `eval/`
