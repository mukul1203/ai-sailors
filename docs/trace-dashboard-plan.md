# Plan: Trace dashboard for real query executions (ai-sailors)

## Context
Every child question runs `run_turn` (src/storyquest/agent/turn.py), which already builds a full `TurnResult` (src/storyquest/agent/trace.py): route, mode, per-LLM-call `StepTrace` (messages, output, tokens, latency, cached), retrieved passages (`SearchHit`, with bm25/dense/rerank ranks), flags and grounding evidence. But `play.ask` (src/storyquest/api/play.py:299) stores only reply, route and flags in `session_events`, and the rest is discarded. The only way to see a trace today is the CLI (`agent/render.py`) or the eval report, which uses golden-set questions, not real ones.

A trace dashboard would let the team see what actually happened on real queries: which route was taken, what was retrieved and in what rank, what the model said, how long and how many tokens each step took, and which flags fired. It supports debugging, the failure-taxonomy work in the report, and the demo.

## Findings that shape the design
- The full trace exists only at `play.py:299`, so persistence must happen there.
- `session_events.kind` has a CHECK (`choice`, `ask`), and the app DB migrates from `src/storyquest/stores/migrations/app/` (next is `0003_*.sql`), run from `create_app` (api/main.py:138).
- There is no auth. Admin routes (`api/admin.py`) are open, so an endpoint exposing child text needs a gate.
- `StepTrace` lacks `finish_reason`, `model` and `reasoning` (available on `LLMResult`, models/llm.py), has no timestamps, and no timing for guard, retrieval or output check.
- A cached step replays the original latency, not the real one (models/cache.py). Throttle wait is not measured (models/throttle.py).
- Privacy: full prompts contain the child's text plus book passages. The LLM disk cache already stores them and `purge-sessions` does not clear it.
- The React app is Vite + react-router + react-query. Tabs are in `web/src/App.tsx`; `Review.tsx` and `Books.tsx` are the admin-page patterns; `api.ts` and `types.ts` hold the client and types.

## Recommended approach

### 1. Capture (backend)
- Add `started_at`, `total_latency_s`, and per-stage timings (guard, router, retrieval, generate, verify, output check) to `TurnResult`, measured with `time.monotonic()` in `run_turn`.
- Extend `StepTrace` with `model` and `finish_reason`. Keep `reasoning` out by default.
- Add a `to_dict()` serialiser for `TurnResult`, `StepTrace` and `SearchHit` in `agent/trace.py`. Reuse the passage fields already used by `evaluation/runner.py::run_item` so live and eval rows share a shape.
- Mark cached steps so the UI shows "replayed latency".

### 2. Persist
- New migration `stores/migrations/app/0003_turn_traces.sql`: table `turn_traces` (`id`, `session_id` REFERENCES sessions ON DELETE CASCADE, `event_id`, `created_at`, `mode`, `route`, `total_latency_s`, `prompt_tokens`, `completion_tokens`, `flags` JSON, `trace` JSON).
- In `play.ask`, after `_event(...)`, write the trace row, wrapped so a trace-write failure never breaks the child's reply.
- Setting `TRACE_STORE` (`off`, `summary`, `full`), default `summary`: summary keeps route, timings, tokens, flags and passage ids; full also keeps prompt messages and model output.
- Extend `purge_sessions` and confirm `PRAGMA foreign_keys=ON` in `stores/db.py` so traces cascade. Add `TRACE_RETENTION_DAYS` for trace-only pruning.

### 3. Read API
- New `api/traces.py`, mounted in `api/main.py` under `/api/admin/traces`:
  - `GET /api/admin/traces`: paged list with filters (mode, route, flag, date range, min latency, cached).
  - `GET /api/admin/traces/{id}`: one full trace.
  - `GET /api/admin/traces/stats`: counts by route, mean and p95 latency, tokens per turn, top flags, retrieval-miss rate.
- Gate with a `TRACE_DASHBOARD` setting (default off) plus a simple admin token (`ADMIN_TOKEN` env var, header check) until real auth exists. Return 404 when off.

### 4. Dashboard UI
- New `web/src/pages/Traces.tsx` and `TraceDetail.tsx`, a "Traces" tab in `App.tsx`, methods in `api.ts`, interfaces in `types.ts`.
- List view: time, mode, route, question (truncated), latency, tokens, flag chips; filters; summary tiles from `/stats`.
- Detail view as a timeline:
  1. question and route
  2. retrieval table: bm25 rank, dense rank, rerank rank, score, spoiler-filter position
  3. each LLM step: tokens, latency, cached, prompt and output (expandable)
  4. grounding evidence
  5. output check flags and the final reply
- Reuse flag explanations from `evaluation/glossary.py` (`explain_flag`) and the plain-language step text from `agent/modes.py::describe_steps`. Render text with React escaping only.
- Optional later: "export as eval item" button to turn a bad real query into a golden-set candidate.

### 5. Privacy and safety
- Admin-only, off by default, retention default 30 days, covered by `purge-sessions`.
- Show a banner on the dashboard that traces contain children's questions.
- Optional redaction pass on stored question text (emails, phone numbers) before saving; list as a follow-up if not in the first cut.
- Document that the LLM cache directory also holds prompts and should be cleared with purge.

## Critical files
- Modify: `src/storyquest/agent/trace.py`, `agent/turn.py`, `api/play.py`, `api/main.py`, `config.py`, `config.env`, `stores/db.py`, `web/src/App.tsx`, `web/src/api.ts`, `web/src/types.ts`
- Add: `stores/migrations/app/0003_turn_traces.sql`, `api/traces.py`, `web/src/pages/Traces.tsx`, `web/src/pages/TraceDetail.tsx`
- Tests: `tests/agent/test_turn.py` (timings and serialiser), `tests/api/test_traces.py` (gating, filters, persistence, purge cascade), `tests/stores` (migration)

## Phases
1. Capture and serialise (no UI): timings, serialiser, migration, persist in `/ask`.
2. Read API with gating, plus stats.
3. React list and detail pages.
4. Privacy hardening: retention, purge coverage, redaction; docs update (README, design doc 06, technical report).

## Verification
- `make check` (ruff, mypy strict, pytest) passes with the new tests.
- Run `make dev-api` and `make dev-web`, play a quest, ask a normal question, an off-topic one and a spoiler-bait one; confirm all three appear with correct route, flags and passage ranks.
- Confirm the dashboard returns 404 when `TRACE_DASHBOARD` is off and 401 without the token.
- Run `storyquest purge-sessions --days 0` and confirm `turn_traces` is empty.
- Compare a traced query's tokens and latency with `storyquest ask` output for the same question.

## Open decisions (defaults chosen)
- Default `TRACE_STORE=summary` (full prompts opt-in).
- Admin token gate now; real accounts later.
- SQLite table in `app.db`, not files, so cascade-purge works.
