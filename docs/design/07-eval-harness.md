# 07 — Evaluation Harness and Reports

Scope: running the live agent against the golden set in different modes and producing human-friendly reports. Items and scoring rules are defined in [../../eval/README.md](../../eval/README.md) and [../../eval/golden_v1.jsonl](../../eval/golden_v1.jsonl).

## Run model

```
storyquest eval run --mode M1 --split dev [--category SPO] [--repeat 3] [--judge-model ...]
storyquest eval report eval/runs/<run_id>
storyquest eval compare eval/runs/<a> eval/runs/<b> [...]
```

Each run writes to `eval/runs/<run_id>/`:

| File | Content |
|---|---|
| `config.json` | Mode flags, model ids, pipeline version, git commit, split, seed |
| `results.jsonl` | One row per item: input, agent output, retrieved chunk ids, tool calls, steps, tokens, latency, scores, failure label |
| `report.html` | Self-contained human report (below) |

## Execution

1. Load items for the chosen split and set the child position from `position` (maps to a beat in the spine).
2. Call the same agent code path as the web app, with the mode config. No eval-only logic in the agent.
3. Record the trace for every item.
4. Score: deterministic checks first, LLM judge second (see the eval doc), then assign one failure label.

## Scoring pipeline

| Layer | Checks |
|---|---|
| Deterministic | JSON schema validity, `must_not_include` strings and regexes, banned tokens, tool-call assertions, step cap |
| Spoiler | Output vs the beat's `spoiler_reveals` list, string match then judge |
| Retrieval | `gold_chunk_hint` present in top-k, reported as recall@k separate from answer quality |
| Judge | Fact coverage, faithfulness to evidence, tone and reading level; the judge sees gold facts and evidence, not the agent's chunks. Spot-check about 20% by hand |

## Report format

A single self-contained HTML file (inline CSS, no server) so it can be shared or opened offline.

Sections:

1. **Summary:** mode, model, date, overall pass rate, headline metrics against targets (green, amber, red).
2. **By category:** table of pass rates for CAN, SPO, SAF and the rest.
3. **Metrics:** fact coverage, faithfulness, spoiler-leak rate, safety pass rate, schema validity, recall@k, steps, tokens, latency p50 and p95.
4. **Failure taxonomy:** counts and examples for retrieval miss, reasoning error, tool-call error, hallucination, spoiler leak, safety failure.
5. **Failures in detail:** per item, the input, expected, actual, retrieved chunks with highlighted evidence, and the trace. Expandable.
6. **Comparison view (for `compare`):** modes side by side, with per-item wins and regressions.
7. **Cost:** tokens and latency per stage.

Dev and test splits are reported separately; test is shown only in the final report.

## Reproducibility

- Temperature 0 by default; `--repeat` runs again and reports variance.
- Record the exact versions listed in `config.json`.
- Disk cache makes reruns cheap, but live-agent evals can bypass it to measure real latency.
- The golden set cites line numbers of the committed Jungle Book fixture; the runner checks the book's hash first.
- With one active request per key, an 80-item run is serial and several calls per item in later modes. Run evals when developers are not using the key, and avoid parallel runs.

## Order of work

1. Runner and deterministic checks.
2. M0 and M1 baselines on dev.
3. Judge and HTML report.
4. Compare mode and the Week 1 baseline write-up.

## Open questions

- Judge model: the same 8B endpoint, or something larger offline (check programme rules).
- Reading-level metric.
- Whether to commit `eval/runs/` or git-ignore it and keep only summaries.
