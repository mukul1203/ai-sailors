# ai-sailors

StoryQuest Copilot: a parent-approved, book-grounded storytelling game for children aged 6 to 9, built on public-domain Project Gutenberg books with a retrieval-augmented agent. Capstone project (Track B: hosted Qwen3-8B, no GPU).

## Documents

- [Capstone brief](docs/capstone-brief.md) and [MVP requirements](docs/mvp-prd.md)
- [Golden eval set plan](eval/README.md); all eval data lives in `eval/`
- [Design docs](docs/design/00-architecture-overview.md) (overview, then one doc per component)

## Getting started

```
make help         # list developer tasks (each has a comment in the Makefile)
make setup        # create .env, venv and dependencies
make doctor       # check tools, secrets and certificate
make check        # data checks, lint, types and tests
```

Secrets go in `.env` (see `.env.example`); settings are in `config.env`.

Try the agent on the Jungle Book (needs the model key and certificate):

```
make seed
make ingest BOOK=236 ARGS="--spine eval/spine_mowgli_brothers.json"
make ask BOOK=236 Q="Who is Tabaqui?" MODE=M1 ARGS="--chapter 0 --beat 0"
make db-viewer    # browse the database at http://localhost:8001
```

Evaluate it and view the HTML report: see [eval/README.md](eval/README.md#0-running-the-evaluation).

The web app, admin area and deployment are not built yet; targets for them print a clear message.
