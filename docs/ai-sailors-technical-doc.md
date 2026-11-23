# StoryQuest Copilot — Technical Report

**Project:** ai-sailors · **Track:** B (hosted Qwen3-8B, no GPU) · **Programme:** upGrad Executive PG in GenAI and Agentic AI
**AI-Sailors Team:** Mukul Agrawal, Mukilan S, Gulshan Nayak, Alok Kumar, Ramya Roy

---

## Contents

- [Abstract](#abstract)
- [1. Problem and Requirements](#1-problem-and-requirements)
- [2. System Architecture](#2-system-architecture)
  - [2.1 Technology stack](#21-technology-stack)
  - [2.2 Why SQLite for everything](#22-why-sqlite-for-everything)
- [3. Data Ingestion and Beat Generation](#3-data-ingestion-and-beat-generation)
  - [3.1 Design choices that reduce small-model risk](#31-design-choices-that-reduce-small-model-risk)
- [4. Retrieval Stack](#4-retrieval-stack)
  - [4.1 Chunking and indexing](#41-chunking-and-indexing)
  - [4.2 Hybrid search](#42-hybrid-search)
  - [4.3 Spoiler filter](#43-spoiler-filter)
  - [4.4 Entity cards (experimental)](#44-entity-cards-experimental)
  - [4.5 Retrieval measurements](#45-retrieval-measurements)
- [5. Agent Design](#5-agent-design)
  - [5.1 Turn flow](#51-turn-flow)
  - [5.2 Modes compared](#52-modes-compared)
  - [5.3 Why grounded answers](#53-why-grounded-answers)
- [6. Model Layer, API, UI and Deployment](#6-model-layer-api-ui-and-deployment)
  - [6.1 Model layer (`src/storyquest/models/`)](#61-model-layer-srcstoryquestmodels)
  - [6.2 API (`src/storyquest/api/`)](#62-api-srcstoryquestapi)
  - [6.3 Frontend (`web/`)](#63-frontend-web)
  - [6.4 Deployment](#64-deployment)
  - [6.5 Trace dashboard](#65-trace-dashboard)
- [7. Evaluation](#7-evaluation)
  - [7.1 Golden set](#71-golden-set)
  - [7.2 Runner and scoring](#72-runner-and-scoring)
  - [7.3 Failure taxonomy](#73-failure-taxonomy)
  - [7.4 Results](#74-results)
- [8. Responsible AI and Safety](#8-responsible-ai-and-safety)
- [9. Limitations and Future Work](#9-limitations-and-future-work)
- [Appendix A. Key Configuration](#appendix-a-key-configuration)
- [Appendix B. Common Commands](#appendix-b-common-commands)
- [Appendix C. Repository Map](#appendix-c-repository-map)
- [Acknowledgements](#acknowledgements)

---

## Abstract

StoryQuest Copilot is a parent-approved, book-grounded storytelling game for children aged 6 to 9. It is built on public-domain Project Gutenberg books. Each chapter is split offline into short "beats": narrated scenes with clues, vocabulary and a "guess what happens next" question. The child plays by choosing answer cards, and can also ask a "sidekick" free-text questions about the story.

Those free-text questions are answered by a retrieval-augmented agent. It uses hybrid retrieval (BM25 plus dense embeddings, fused with reciprocal rank fusion, optionally reranked by a cross-encoder), a spoiler filter enforced inside the SQL query, a router that deflects unsafe or off-topic input, sentence-level grounded answers, and a rule-based output check. The generator is Qwen3-8B on a shared hosted endpoint, so the design compensates for a small model with code-side checks instead of larger prompts.

On an 80-item golden set (47 dev items run), a no-retrieval baseline (M0) passed 49%. The grounded retrieval modes (M1S, M2S) passed 64%. Embedding scene context raised gold-passage recall from 15/23 (keyword only) to 20/23. Section 7 explains the measurement limits.

---

## 1. Problem and Requirements

Generic chatbots fail a child reading a specific book in five ways (`docs/mvp-prd.md`):

1. They **hallucinate** plot details.
2. They **blend in film adaptations** (for example Disney's Jungle Book).
3. They **drift into adult vocabulary**.
4. They **spoil later chapters**.
5. They **keep no game state**, so they cannot tell how far the child has read.

**Requirements derived from the capstone brief** (`docs/capstone-brief.md`):

| Requirement | How the project addresses it |
|---|---|
| Gold evaluation set of 60–100 items | 80-item golden set, 10 categories (Section 7) |
| At least 3 prompting strategies compared | Modes M0–M4S (Section 5) |
| Hybrid retrieval with reranker, recall@k measured separately | BM25 + dense + RRF + cross-encoder; `make eval-retrieval` |
| Agentic layer with a bounded step count | Linear pipeline with router, grounding and output check (see limitations) |
| Failure taxonomy | Eight failure labels (Section 7) |
| UI, container, rate limiting, caching | React app, Docker, throttled and cached model client (Section 6) |
| Responsible-AI section | Section 8 |

**Product constraints.** No spoilers beyond the child's current position. No film content. Reading level at or below Flesch-Kincaid grade 8. A human reviews generated content before a child sees it.

---

## 2. System Architecture

The system has two flows that share one idea: **position**, the pair (chapter index, beat index). Position drives the spoiler filter, retrieval, resume and evaluation setup.

![StoryQuest Copilot system architecture](images/architecture.png)

*Figure 1. System architecture: the offline ingestion pipeline feeds the content database; each live turn reads it through a position filter.*

### 2.1 Technology stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ (built on 3.12); no LangChain or LangGraph, the agent is hand-rolled |
| API | FastAPI, served by uvicorn |
| LLM | `Qwen/Qwen3-8B` on vLLM behind an OpenAI-compatible endpoint |
| Embeddings | `bge-small-en-v1.5` (384 dimensions) via the course endpoint; Gemini `gemini-embedding-001` as an alternative |
| Keyword search | SQLite FTS5, porter stemmer, BM25 |
| Vector search | float32 vectors stored in SQLite, cosine computed in Python |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` via sentence-transformers |
| Frontend | React 19, TypeScript, Vite, react-router, react-query |
| Packaging | Multi-stage Docker build, docker-compose, Makefile |

### 2.2 Why SQLite for everything

A single book has thousands of chunks, not millions. A linear cosine scan over the visible chunks is fast at that scale, and keeping text, FTS index, vectors and the spoiler filter in one database makes the position filter a single `WHERE` clause. The cost is that dense search will not scale to a large corpus; Section 9 lists this.

Two databases are kept apart on purpose:

- `var/content.db`: rebuildable from the books, shared by all users.
- `var/app.db`: sessions and events, which are not rebuildable.

---

## 3. Data Ingestion and Beat Generation

Ingestion (`src/storyquest/ingestion/`) turns a raw Gutenberg text into reviewed, searchable, child-friendly beats. It runs as a resumable pipeline; each step records an input hash in `ingestion_steps`, so reruns skip finished work.

| Stage | Module | What it does |
|---|---|---|
| 1 Verify | `pipeline.py` | SHA-256 of `raw.txt` against the book record |
| 2 Clean | `text.py` | Keeps the text between the Gutenberg START and END markers, normalises quotes, keeps an offset map |
| 3 Chapters | `chapters.py` | Uses the Contents list with fuzzy heading match (0.9 similarity); falls back to one story |
| 4 Classify | `chapters.py` | Story or poem, by length and line shape |
| 5 Segment | `segment.py` | An LLM proposes scene starts from 60 numbered paragraph openings. A dynamic program picks boundaries nearest 3,500 characters within 1,800–6,500. Fallback is size-only splitting |
| 6 Generate | `beatgen.py` | Two LLM calls per beat: a retelling (title, narration, 3–5 clues with verbatim quotes, vocabulary) and a "guess what happens next" question (one right answer, two wrong, two hints) |
| 7 Validate | `validate.py` | Code only. Described below |
| 8 Entities | `entities.py` | Characters, places and terms per beat, kept only if the name appears in the text |
| 9 Chunk and embed | `chunking.py`, `embed.py` | About 500-character chunks that never cross a beat boundary; embedded in resumable batches of 50 |
| 10 Review | `review.py`, admin API | A human approves each beat |
| 11 Publish | `review.py` | Requires every story chapter to be approved and chunked |

### 3.1 Design choices that reduce small-model risk

- **Code builds the facts that must be right.** The answer position is shuffled in code. The `spoiler_reveals` list (things the child must not be told yet) is built from later beat and chapter titles, not generated by the model.
- **Validation is deterministic** (`validate.py`):
  - every clue quote must trace back to the book text;
  - readability must be at or below Flesch-Kincaid grade 8;
  - a safety word list (`prompts/safety_terms.txt`) is applied;
  - question rules are checked: one right answer supported by the next scene, no meta wording, hints that do not leak the answer.
- **Retry with feedback.** Up to two retries pass the problems back to the model. Untraceable clues are dropped and the beat is flagged. A failing question falls back to a plain "Yes, let's go!" card.
- **Human review gate.** Flagged beats need explicit per-beat approval, so a child never sees unreviewed content.
- **Reproducibility.** `version.py` hashes prompts, model, settings and the safety list into a `pipeline_version`. Hand-written "spine" beats for Chapter 1 of the Jungle Book (`eval/spine_mowgli_brothers.json`) serve as a yardstick for the segmenter and are never overwritten without `--force`.

---

## 4. Retrieval Stack

Retrieval answers the child's free-text questions. It has four parts and a hard filter.

### 4.1 Chunking and indexing

Chunks are exact text slices of about 500 characters, packed from paragraphs and never crossing a beat boundary. Paragraphs over 1,800 characters are split on sentences. Each chunk is stored with its chapter and beat index, so every chunk carries its own position.

### 4.2 Hybrid search

1. **BM25** over SQLite FTS5, with a stopword-stripped OR query.
2. **Dense search** with `bge-small-en-v1.5`. Each chunk is embedded together with neighbours from the same beat, up to 1,200 characters ("scene context"), because a short chunk alone often lacks the subject of the sentence.
3. **Reciprocal rank fusion** with k = 60. Each retriever contributes 20 candidates and the fused list is cut to the top 6 (`stores/search.py::hybrid_search`).
4. **Optional cross-encoder rerank** of the 20 fused candidates down to 6 (`models/reranker.py`).

If embedding fails or no vectors exist, retrieval degrades to keyword search and records a flag (`embedding_error`, `no_vectors`) on the trace instead of failing the turn.

### 4.3 Spoiler filter

The filter runs **inside the SQL query**, so spoilers cannot be retrieved at all, rather than being removed afterwards:

```sql
chapter_idx < :c OR (chapter_idx = :c AND beat_idx <= :b)
```

The server owns the child's position; the client never sends one. A second, code-side check in the output stage catches proper names that first appear at or after the child's position.

### 4.4 Entity cards (experimental)

For modes M3 and above, up to two entity cards are added when the child names a character or place. A card is used only if the child has reached both the name's first occurrence and the beat the card was written from. This mode is experimental because a card can win the model's attention over the book sentences.

### 4.5 Retrieval measurements

Measured on the dev split, mode M2S, top 6, over 23 questions that have a gold passage and 47 gold facts (README, measured 16 Nov 2026):

| Embeddings | Gold passage found | Fact evidence found | M2S pass rate |
|---|---|---|---|
| None (M1S, keyword only) | 15/23 | 28/47 | 62% |
| Gemini `gemini-embedding-001` | 22/23 | 45/47 | 66% |
| bge-small, chunk alone | 18/23 | 35/47 | 62% |
| bge-small, chunk alone + query prefix | 18/23 | 35/47 | 64% |
| **bge-small + scene context (default)** | **20/23** | **42/47** | **66%** |

Findings:

- Scene context is the largest single improvement for the course embedding model.
- A top-k of 8 found 32/47 facts but cost 19% more prompt tokens, so k stayed at 6.
- Tuning RRF k and the candidate count changed nothing.
- A difference of one or two questions is noise at this sample size.
- **No reranker (M4/M4S) numbers have been recorded yet.** The reranker is implemented and tested, but its effect is unmeasured. This should be run before submission with `make eval-retrieval` and `make eval MODES="M2S M4S" SPLIT=dev`.

---

## 5. Agent Design

The live agent (`src/storyquest/agent/turn.py::run_turn`) is a linear pipeline. Every decision that can be made by code is made by code, because the generator is an 8B model with an 8,192-token window.

### 5.1 Turn flow

1. **Guard** (`guard.py`): an empty message, or one over 300 characters, gets a canned reply with no model call.
2. **Router** (`router.py`): one model call, at most 30 output tokens, constrained to a JSON-schema enum: `story_question`, `feelings`, `off_topic`, `unsafe`, `injection`, `personal`. Anything except `story_question` receives a fixed, pre-written, child-friendly reply (`replies.py`). If the label cannot be parsed, the default is `story_question`.
3. **Retrieve** (`retrieval.py`): as in Section 4. No hits gives "I don't know that yet".
4. **Generate** (`generate.py`): the system prompt carries the title, author, chapter and beat. The child's text is wrapped in `<child_message>` markers as an injection defence. Temperature is 0.
5. **Ground** (`grounding.py`, "S" modes): each retrieved passage is split into numbered sentences such as `[2.3]`. The model returns JSON `{evidence: [ids], answer}`, with ids restricted by an enum and at most 3. Code checks the ids. With no valid evidence the reply is "unknown yet".
6. **Output check** (`output_check.py`, no model call): flags banned film terms (for example disney, cartoon, movie) unless the child used them, and flags names that first appear at or after the child's position. A failure produces a safe "careful" reply.
7. **Trace** (`trace.py`): records every step, the messages, token counts, latency, cache hits, passages, flags and evidence, plus the start time, total latency and the time spent in each stage. In the live app each trace is saved and shown on the trace dashboard (Section 6.5).

### 5.2 Modes compared

| Mode | Retrieval | Hybrid | Entity cards | Rerank | Grounded |
|---|---|---|---|---|---|
| M0 | no | | | | |
| M1 | BM25 | | | | |
| M1S | BM25 | | | | yes |
| M2 | yes | yes | | | |
| M2S | yes | yes | | | yes |
| M3 / M3S | yes | yes | yes | | S only |
| M4 / M4S | yes | yes | yes | yes | S only |

The API degrades gracefully when a resource is missing: M2/M3/M4 fall back to M1, the S modes to M1S, and M4/M4S to M2/M2S when no reranker is installed (`api/main.py::_choose_mode`).

### 5.3 Why grounded answers

Free-form answers from a small model can sound right while stating something the book does not say. The grounded modes make the model cite sentence ids, and code verifies that the ids exist. This turns "is the answer supported?" from a judgement into a check. The trade-off is a higher "unknown yet" rate when retrieval misses the passage.

---

## 6. Model Layer, API, UI and Deployment

### 6.1 Model layer (`src/storyquest/models/`)

A single `LLMClient` protocol with one `chat()` method is wrapped by decorators:

```
CachedClient -> ThrottledClient -> OpenAICompatibleClient
```

- **Cache:** disk cache keyed by the SHA-256 of model, messages, max tokens, schema and extra body. Used only at temperature 0.
- **Throttle:** one concurrent request and a minimum gap derived from requests per minute. The shared endpoint allows 1 concurrent request and 60 requests per minute.
- **Client:** sends `response_format=json_schema` with `strict: true`, strips `<think>` blocks, and retries 429 and 503 responses after 2, 4 and 8 seconds. TLS is verified against a private CA certificate.
- **Fakes:** `FakeClient`, `FakeEmbedder` and `FakeReranker` let the whole test suite run without network access.

### 6.2 API (`src/storyquest/api/`)

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Model configured, active mode |
| `GET /api/library` | Books with per-chapter state (playable, prepared, preparing, failed) |
| `POST /api/library/{book}/chapters/{idx}/prepare` | Queue the LLM ingestion stages |
| `POST /api/admin/books` | Upload a Gutenberg text with metadata |
| `GET /api/admin/books/{id}/review`, `POST .../approve`, `POST .../publish` | Review and publish |
| `GET /api/missions` | Playable chapters |
| `POST /api/sessions`, `GET /api/sessions/{id}` | Start and resume a quest |
| `POST /api/sessions/{id}/choice` | Answer card. No model call; two wrong tries with hints, then the answer is revealed |
| `POST /api/sessions/{id}/ask` | Runs the live agent and saves its trace |
| `GET /api/admin/traces`, `/stats`, `/{id}` | Trace list with filters, summary statistics, one full trace. Off by default and token-gated (Section 6.5) |

Operational limits: at most 10 questions per session and a 2-second minimum interval between questions. If the model key is missing, the sidekick reports it is "resting" while answer cards still work. Every response carries `Content-Security-Policy: default-src 'self'`, `nosniff` and `no-referrer`. API docs appear only when `API_DEBUG=true`.

### 6.3 Frontend (`web/`)

Four tabs: **Play**, **Books**, **Review** and **Traces**. The Traces tab appears only when the server has the trace dashboard switched on.

- **Quest** page: narration, clues, vocabulary, lettered answer cards, hints, a questions-left counter, a "Read to me" button using browser speech synthesis, an ask-the-sidekick form, and resume through `localStorage`.
- **Books** page: add a book, see chapter state, and prepare one or all chapters with progress polling.
- **Review** page: the human-in-the-loop view, showing narration, question, cards, hints and flags; approve one beat or all clean beats; publish with blocking problems shown.
- **Traces** page: the grown-ups' view of real questions (Section 6.5).

Server text is written with `textContent` only.

### 6.4 Deployment

- **Dockerfile:** a Node stage builds the web app; a Python 3.12-slim stage serves it. The `WITH_RERANKER` build argument controls whether CPU torch and the cross-encoder are baked in. The container runs as a non-root user with a `/data` volume and a health check.
- **docker-compose:** two services, `app` and `worker`, sharing one image. `make up` starts the app.
- **Makefile:** about 40 self-documenting targets for setup, run, quality checks (`make check` runs lint, mypy strict and tests), data, evaluation and SSH deployment.
- **Configuration:** `config.env` (committed) is overridden by `.env` (secrets) and then by real environment variables.

### 6.5 Trace dashboard

Before the dashboard, the full trace of a turn existed only in the CLI and the evaluation report, which use golden-set questions. The live `/ask` handler discarded everything except the reply, route and flags. The dashboard saves and shows what happened on real questions, to support debugging, the failure taxonomy and the demo.

- **Capture.** `run_turn` records its start time, total latency and per-stage timings (guard, router, retrieval, generate, verify, output check). Each model call also records its model and finish reason. A cached call keeps the latency of the original call, so the UI labels it "replayed".
- **Storage.** `play.ask` writes one row per question to the `turn_traces` table in `app.db` (migration `0003_turn_traces.sql`). The row cascades with its session. A failure to save a trace is logged and never affects the child's reply.
- **`TRACE_STORE`.** `summary` (default) keeps route, timings, tokens, flags and passage ids and ranks. `full` also keeps prompts, model output and passage text. `off` saves nothing.
- **Read API.** `api/traces.py` serves a paged, filterable list (mode, route, flag, date range, minimum latency, replayed), one full trace, and statistics: counts by route, mean and p95 latency, tokens per turn, top flags and the retrieval-miss rate.
- **Access.** Traces contain children's questions. The API returns 404 unless `TRACE_DASHBOARD=true`, and then requires the `ADMIN_TOKEN` in an `X-Admin-Token` header. An unset token admits nobody. This is a stop-gap until the app has accounts.
- **Retention.** Traces are deleted with their session by `purge-sessions`, and traces older than `TRACE_RETENTION_DAYS` (30) are pruned at app start and by `purge-sessions`.
- **UI.** The list page has summary tiles, filters and a table. The detail page follows the turn in order: question and route with stage timings, retrieval table (BM25, meaning and rerank ranks, score, book position), each model call (expandable prompt and output in `full` mode), grounding evidence, then flags with plain-language explanations and the reply the child saw.

The dashboard already exposed a real fault: two M4S questions carried a `reranker_error` flag because `sentence-transformers` was not installed, so they were answered without reranking and should not count as M4S results.

---

## 7. Evaluation

### 7.1 Golden set

`eval/golden_v1.jsonl` has 80 items on a fixture of *The Jungle Book*, Chapter 1 ("Mowgli's Brothers"), split about 60/40 into dev and test. The test split is reserved for final reporting.

| Code | Category | Items |
|---|---|---|
| CAN | In-chapter canon Q&A | 20 |
| CHR | Character and vocabulary | 8 |
| SPO | Spoiler traps | 12 |
| OOC | Not in the book | 6 |
| DIS | Disney contamination | 6 |
| FLO | Quest flow | 8 |
| SAF | Child safety | 8 |
| INJ | Prompt injection | 6 |
| PII | Personal information | 3 |
| MAL | Malformed input | 3 |

Each item carries the facts an answer must include, evidence as line ranges with exact quotes, forbidden content and expected behaviour. `make check-data` verifies the quotes against the fixture and the book hash. Five items (FLO-001, FLO-004, FLO-006, FLO-007, INJ-004) need a full session or an injected passage and are skipped.

### 7.2 Runner and scoring

The runner calls the same agent code path as the web app and records the trace, tokens, latency, git commit, embedding model and golden-set hash.

An item **passes** when all of these hold:

- the behaviour is right (answered, or deflected where expected);
- there are no forbidden words or spoilers;
- judge recall is at least 0.5;
- faithfulness is 100%.

The LLM judge makes three separate calls per item:

- **Recall:** the share of required facts stated.
- **Claims:** the reply is split into at most 8 claims.
- **Verify:** each claim is checked against the retrieved passages, and every "yes" needs a quote. At least 80% of that quote's words must occur in the cited text.

### 7.3 Failure taxonomy

| Label | Meaning |
|---|---|
| `error` | The turn failed |
| `wrong_route` | Router sent the message to the wrong branch |
| `retrieval_miss` | The gold passage was not retrieved |
| `over_deflection` | Deflected a question that should have been answered |
| `leak` | A spoiler or forbidden content appeared |
| `missing_facts` | Answer lacked required facts |
| `unfaithful` | A claim was not supported by the passages |
| `no_deflection` | Answered something that should have been deflected |

### 7.4 Results

Stored run `20261116-213024`, dev split, 47 items run (commit e9e9ae0):

| Mode | Pass rate | Judge recall (mean) | Notes |
|---|---|---|---|
| M0 (no retrieval) | 23/47 (49%) | 0.21 | In-chapter Q&A 2/13; `no_deflection` and `missing_facts` dominate |
| M1S | 30/47 (64%) | 0.45 | Faithfulness 16/21 |
| M2S | 30/47 (64%) | 0.45 | bge-small with scene context |

- In all three modes the gold passage reached the top 6 for 15 of 23 questions (65%).
- Safety (4/5), injection (3/3), personal information (2/2) and malformed input (2/2) were the same in every mode, because the router and guard handle them before retrieval.
- Cost per item is about 1.7 model calls, 877 prompt tokens and 46 completion tokens, at about 1.2 seconds.

**Caveats that apply to these numbers:**

- The M1S and M2S summaries in the stored run are identical even though M2S used different embeddings. This should be checked before the figures are quoted as a real tie.
- The README's separate ablation reports 62% and 66% for these modes; the difference comes from separate runs and is within noise.
- The judge is the same Qwen3-8B that writes the answers, so verdicts are noisy, and a 100% faithfulness bar can fail on a single wrong verdict.
- The evaluation covers one chapter of one book. The test split has not been reported.

---

## 8. Responsible AI and Safety

| Risk | Control |
|---|---|
| Spoilers | Position filter inside the SQL query; name-based output check; `spoiler_reveals` built by code |
| Hallucination | Grounded answers with verified sentence ids; "I don't know that yet" when nothing is retrieved |
| Film contamination | Banned-term output check; retrieval limited to the book text |
| Unsafe or off-topic input | Router labels with fixed, pre-written replies; no model text reaches the child on those paths |
| Prompt injection | `<child_message>` markers, a 300-character input cap, an `injection` router label, a content security policy |
| Inappropriate content in generated beats | Safety word list, reading-level check, and a human approval gate before publish |
| Privacy | The agent never asks for personal details; a `personal` route deflects them; sessions use random tokens |
| Over-use | 10 questions per session, 2-second minimum interval |
| Retention | Child text is kept in `session_events` until `storyquest purge-sessions --days N` is run. Traces are also pruned after `TRACE_RETENTION_DAYS` (30) |
| Trace access | The trace dashboard is off by default and, when on, needs an admin token. Prompts and passage text are stored only with `TRACE_STORE=full` |

The router and output check use no free-form generation for refusals, so a deflection cannot itself be manipulated.

---

## 9. Limitations and Future Work

**Not yet built**

- **Accounts and parent controls.** There is no authentication; admin routes are open, except the trace dashboard, which is gated by a shared admin token. Parent profiles, child profiles, badges and per-child session caps exist only in the design docs. `SESSION_SECRET` is not yet used.
- **Planner, executor and critic loop.** The agent is a single linear pipeline. The non-LLM output check plays the critic's role, but there is no iterative step budget and no tool calls such as `retrieve_canon` or `award_badge`.
- **PII redaction** in stored traces. Trace retention is automated, but the LLM disk cache also holds prompts and is not cleared by `purge-sessions`.
- **CI.** There is no workflow; `make check` is run by hand.

**Evaluation gaps**

- Reranker modes M4/M4S have no recorded results, even though `config.env` sets `PLAY_MODE=M4S`.
- One chapter of one book; the test split is unreported; five items are skipped.
- The capstone brief suggests a corpus of 500–2,000 documents, and only the Jungle Book fixture is committed. Ingestion of other books is supported but not evaluated.
- The judge is the same model as the generator, and its thresholds are hand-picked.

**Technical limits**

- Dense search is a linear scan in Python. It is fine at book scale and will not scale to a large corpus.
- The shared endpoint allows one concurrent request, so ingestion and live play compete when `INGEST_IN_API=true`.
- Three of 23 gold passages are still missed with the default embeddings.
- Entity cards sometimes hurt answers.
- A forced rebuild replaces beats rather than keeping versions side by side.
- Story-versus-poem classification is a heuristic.

**Next steps**

1. Run `make eval` for M4S on dev and test splits and report the reranker's effect.
2. Add a second book and a second eval fixture.
3. Add a small authenticated parent area and automated session purging.
4. Replace the same-model judge, or add a human-labelled subset to calibrate it.
5. Add CI running `make check`.
6. Replace the linear scan with an approximate index if the corpus grows.

---

## Appendix A. Key Configuration

| Setting | Default |
|---|---|
| `LLM_MODEL` | `Qwen/Qwen3-8B` |
| `LLM_MAX_CONCURRENCY` / `LLM_REQUESTS_PER_MINUTE` | 1 / 50 |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` | `bge-small-en-v1.5` / 384 |
| `EMBEDDING_CONTEXT_CHARS` | 1200 |
| `CHUNK_TARGET_CHARS` / `CHUNK_MAX_CHARS` | 500 / 1800 |
| `BEAT_TARGET_CHARS` (min / max) | 3500 (1800 / 6500) |
| `RETRIEVAL_CANDIDATES` / `RETRIEVAL_TOP_K` / `RRF_K` | 20 / 6 / 60 |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| `GENERATION_MAX_TOKENS` | 200 |
| `MAX_CHILD_INPUT_CHARS` | 300 |
| `MAX_QUESTIONS_PER_SESSION` / `ASK_MIN_INTERVAL_SECONDS` | 10 / 2 |
| `PLAY_MODE` | `M4S` (set in `config.env`) |
| `TRACE_STORE` / `TRACE_DASHBOARD` / `TRACE_RETENTION_DAYS` | `summary` / `false` / 30 |
| `ADMIN_TOKEN` | unset (in `.env`; needed to open the trace dashboard) |

## Appendix B. Common Commands

| Task | Command |
|---|---|
| Install and configure | `make setup`, then edit `.env` |
| Check connectivity | `make doctor`, `make llm-ping` |
| Load demo data | `make demo-data` |
| Run the app locally | `make dev-api` (http://localhost:8000) |
| Run in containers | `make up` |
| Ingest a book | `make ingest-llm`, `make review`, `make approve`, `make publish` |
| Evaluate | `make eval`, `make eval-retrieval`, `make eval-report` |
| Quality gate | `make check` |

## Appendix C. Repository Map

```
src/storyquest/
  ingestion/   text, chapters, segment, beatgen, validate, entities, chunking, embed, pipeline
  stores/      db, content_repo, search (FTS5 + RRF), vector, traces, migrations
  models/      llm, openai_compatible, throttle, cache, embedder, reranker, fake
  agent/       modes, turn, router, guard, retrieval, grounding, generate, output_check, trace
  api/         main, play, library, admin, traces
  evaluation/  runner, scoring, judge, retrieval, report, html_report
web/           React app (Library, Quest, Books, Review, Traces)
eval/          golden_v1.jsonl, Jungle Book fixture, spine beats, runs
docs/          capstone brief, PRD, design docs 00-10
tests/         about 287 test functions
```

---

## Acknowledgements

We extend our heartfelt thanks to all the professors and mentors who guided us through the Executive PG Programme in Generative AI and Agentic AI. Your lectures, live sessions, feedback and patience gave us the foundations in retrieval, prompting, evaluation and agentic design that this project is built on.

Thank you for encouraging us to question results, measure what we build and design responsibly. This work is a direct outcome of what we learned from you, and we are grateful for the time and care you invested in our learning journey.

**With gratitude, Team AI-Sailors**
