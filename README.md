# ai-sailors

StoryQuest Copilot: a parent-approved, book-grounded storytelling game for children aged 6 to 9, built on public-domain Project Gutenberg books with a retrieval-augmented agent. Capstone project (Track B: hosted Qwen3-8B, no GPU).

## Documents

- [Capstone brief](docs/capstone-brief.md) and [MVP requirements](docs/mvp-prd.md)
- [Golden eval set plan](eval/README.md); all eval data lives in `eval/`
- [Design docs](docs/design/00-architecture-overview.md) (overview, then one doc per component)

## Getting started

```
make help         # list developer tasks
make setup        # create .env, venv and dependencies
make doctor       # check tools, secrets and certificate
make check-data   # validate the golden set, spine and Jungle Book fixture
```

Secrets go in `.env` (see `.env.example`); settings are in `config.env`.

The application code is not written yet; targets that need it print a clear message.
