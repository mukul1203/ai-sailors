# StoryQuest: 10-minute demo script

Presenter: Mukilan. Runs on the course endpoint (Qwen3-8B). Timings are targets; the whole
script is about 9 minutes, leaving a minute for slack.

## Before the demo (the day before, and again an hour before)

1. `.venv/bin/storyquest eval preflight` (and `make doctor`): the chat model and the embeddings must both say `ok`.
2. Publish the Jungle Book in the data folder you will demo from (`make publish BOOK=236`, or
   the Review tab) and run `make embed BOOK=236` once. An unpublished book is not listed on
   the Play tab.
3. Set in `.env` for the demo: `PLAY_MODE=M5` (already the default in `config.env`),
   `TRACE_DASHBOARD=true`, `ADMIN_TOKEN=<a fresh secret>`, `API_DEBUG=false`.
4. Optional, for the OpenTelemetry part: `make jaeger` and add
   `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318` to `.env`.
5. `make build-web`, then `make dev-api`, and open http://localhost:8000.
6. **Rehearse every question below once.** Answers are cached, so on stage the same questions
   come back at once and identically even if the shared endpoint is slow; the trace dashboard
   marks such turns "replayed", so say so if asked.
7. Keep a screen recording of the rehearsal as a fallback if the endpoint is down on the day.

## Script

### 1. The problem (1 minute, slides or talk)
- A child asks a plain chatbot about The Jungle Book: it invents facts, mixes in the Disney
  film (King Louie is not in the book) and spoils the ending.
- StoryQuest: a book-grounded story game for ages 6 to 9, on a small 8B model with no GPU,
  where every answer must come from the pages the child has already read.

### 2. Play a quest (2 minutes)
- Play tab: The Jungle Book, chapter "Mowgli's Brothers".
- Read the first scene aloud, answer the "what happens next?" card once wrong (the hint
  appears) and once right (the story moves on).
- Point out: the scenes, clues and questions were written offline by the model, checked by
  code against the book text, and approved by a person before any child sees them.

### 3. The sidekick, at the second scene (3 minutes)
Ask, in this order. Each was tried at the second scene on a local Qwen3-8B on 24 Nov; rehearse them on the course endpoint, which may word replies differently.

| Ask | What it shows |
|---|---|
| "Who is Shere Khan?" | A grounded answer from the book (tiger, Waingunga River) |
| "Why does he limp?" | Memory: "he" is understood as Shere Khan; answer cites "lame in one foot from his birth" |
| "Does he die in the end?" | Spoiler safety: "I don't know that yet", because the search can only see pages already read |
| "Does Baloo sing The Bare Necessities?" | Film contamination: no film song is attributed; Baloo has not appeared by this scene, so the reply is "I don't know that yet" |
| "My name is Aarav and I live at 12 Rose Street" | Privacy: a fixed reply, and the message is not remembered |

### 4. Under the hood: the trace dashboard (2 minutes)
- Traces tab, enter the admin token, open the trace of "Why does he limp?".
- Show, top to bottom: the route; **the tools the agent ran** (the question searched as
  "Why does Shere Khan limp?" plus `lookup_character`); the passages and their ranks; each
  model call (planner, answer, critic); the cited evidence; the flags; the reply.
- One sentence on guardrails: at most 10 steps and 8,000 tokens per question, one critic
  revision, tools that can only read and only up to the child's position.
- If Jaeger is running: click "open in Jaeger" on the same trace. The same turn as a
  standard OpenTelemetry trace, a timeline of guard, router, planner, tools, answer and
  critic, with no child text in it; the shared trace id leads back here to the message.

### 5. How we know it works (1 minute)
- The golden set: 80 questions in 10 categories, gold answers with line-level evidence.
- Paste the table from `make final-eval` (dev and test) and say the one-line findings:
  [TBD: M2S vs M4S vs M5 pass rates]; scene context raised gold-passage recall from 15/23
  (keyword only) to 20/23; the reranker helps the top 3, not the top 6.
- Prompting: few-shot, chain-of-thought and decomposition prompts on the same retrieval were
  within noise of zero-shot, in M2S and inside the agent; the agent's plain answer prompt
  stayed best [TBD: confirm on the course endpoint].
- One honest limit: the agent costs about three model calls a question, so it is slower.

### 6. Close (30 seconds)
- Built entirely on the provided 8B endpoint and embeddings; what we did for a small model is
  in the report (Section 5.5). Questions.

## If something goes wrong
| Problem | Do this |
|---|---|
| Endpoint slow | Ask only rehearsed questions (they replay from the cache) |
| Endpoint down | Play the rehearsal recording; the trace dashboard and Play tab still work offline for cached turns |
| A reply is "I don't know that yet" for a fair question | Say it fails safe by design: the critic would rather refuse than let an unsupported fact through |
