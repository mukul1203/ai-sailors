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

You need Python 3.11+ and `make`. You also need three things from the team: the model key and URL,
the CA certificate, and (for hybrid search only) a free Gemini API key from Google AI Studio.

```
make setup        # creates .env, the virtual environment and installs everything
```

1. Edit `.env` (git-ignored): `LLM_API_KEY`, `LLM_BASE_URL`, and optionally `EMBEDDING_API_KEY`.
2. Put the certificate at `certs/ca.crt`.
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

   Locally the page lists every chapter that has beats (`PLAY_UNPUBLISHED=true` in `config.env`).
   Without that setting only published books with approved beats are listed. Without a model key
   you can still click through the quest; the sidekick just says it is resting.

7. Evaluate and read the report (opens in your browser, takes a while: the model endpoint handles
   one request at a time):

```
make eval                            # M0, M1S and M2S on the dev split
make eval MODES="M1 M1S M2 M2S"      # compare keyword and hybrid retrieval
make eval ARGS="--category SPO --limit 5"   # a quick subset
```

Everything has a `make` target; `make help` lists them all, and each target has a comment in the
[Makefile](Makefile) explaining what it does.

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

| Mode | Retrieval | Evidence sentences | Needs `EMBEDDING_API_KEY` |
|---|---|---|---|
| M0 | none (plain model) | no | no |
| M1 | keyword (BM25) | no | no |
| M1S | keyword (BM25) | yes: the model picks the numbered sentences it relies on | no |
| M2 | hybrid: keyword plus meaning, fused by reciprocal rank fusion | no | yes |
| M2S | hybrid | yes | yes |
| M3 / M3S | hybrid, plus entity cards for named characters, places and terms | no / yes | yes, and `make ingest-llm` for the cards |

M2S is the best so far (72% on the dev split). M3S, the entity-card variant, scored 68% in its first
run: the card for a name ("Akela is the leader of the wolf pack") can win the model's attention
over the book sentences that hold the exact facts, so M3 and M3S are experimental.

Hybrid modes need `make embed BOOK=<id>`
once per book, and again after `make ingest` rebuilds the chunks (`make demo-data` does both).
If the vectors are missing, hybrid modes fall back to keyword search and the turn carries the flag
`no_vectors`. The free Gemini tier has a daily embedding quota: `make embed` stores each batch as
it goes, earliest chapter first, and resumes where it stopped.

## Configuration

- Secrets go in `.env` (see [.env.example](.env.example)). It is git-ignored.
- Settings are in [config.env](config.env), with a comment per group: chunk size (500
  characters), passages per turn (`RETRIEVAL_TOP_K`, 6), model and embedding settings.
- Settings you set in your shell win over both files, for example
  `RETRIEVAL_TOP_K=3 make eval MODES=M2S`.
- Runtime data (databases, model and embedding caches, eval runs) lives in `var/` and
  `eval/runs/`, both git-ignored. `make db-reset` deletes the databases; `make demo-data` rebuilds
  them.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `make doctor` says MISSING | add the value to `.env`, or the certificate to `certs/ca.crt` |
| `make ask ... MODE=M2S` says it needs an embedder | set `EMBEDDING_API_KEY` in `.env`, then `make embed BOOK=236` |
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
