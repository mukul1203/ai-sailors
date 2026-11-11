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

## Built so far (text runner, deterministic checks)

`make eval MODE=M1 SPLIT=dev` runs every non-skipped item through the agent and saves `config.json`, `results.jsonl` and `summary.txt` under `eval/runs/<mode>-<split>-<time>/`. `make eval-compare RUNS="<run a> <run b>"` shows two runs side by side.

- **Skipped items:** those marked `skip` in the golden file need a full quest session (choice clicks, idle time, session cap) or an injected poisoned passage, so they wait for step 8.
- **Behaviour check:** answered, deflected, refused, asked to clarify or reassured, judged from the route and reply.
- **Forbidden words:** literal `must_not_include` entries are matched as whole words. A term the child used themselves may be repeated. Entries that describe content (for example "invented smells") are counted as unchecked.
- **Facts:** a keyword proxy at first. It misses correct answers that use different words, so it is only a lower bound until the judge has run.
- **LLM judge** (`make eval-judge RUN=...`, or `--judge` on `eval run`): for items expecting an answer, and for descriptive forbidden-content rules, the model sees the question, the reply and the gold book lines (never what the agent retrieved). It says which expected facts the reply states, whether it contradicts or invents details beyond the book text, and whether each descriptive rule is violated. Every "yes" must come with a quote copied from the reply, and code checks the quote really is in the reply; a verdict without a real quote counts as "no". Pass or fail is then recomputed from facts, forbidden content and behaviour; the contradiction flag is shown in the report as a hint and does not fail an item, because the model over-flags it. The judge is the same Qwen3-8B as the agent, so it is noisy: it can flag true details that lie outside the gold lines. Use the numbers for comparing modes, and spot-check items in the report.
- **Scoring reference:** every rule, threshold and failure label that decides a result is in [10-scoring-reference.md](10-scoring-reference.md).
- **HTML report** (`make eval-report RUN=... ARGS="--against <other run>"`): one self-contained `report.html` per run with summary cards, pass rate per category (with change against a baseline run), failure causes, and every item expandable with its reply and scores.
- **Retrieval:** whether plain retrieval put the gold lines in the top passages, computed without the model.
- **Failure causes:** `retrieval_miss`, `over_deflection`, `wrong_route`, `missing_facts`, `wrong_facts`, `no_deflection`, `leak`, `error`.

## Order of work

1. Runner and deterministic checks.
2. M0 and M1 baselines on dev.
3. Judge and HTML report.
4. Compare mode and the Week 1 baseline write-up.

## Open questions

- Judge model: the same 8B endpoint, or something larger offline (check programme rules).
- Reading-level metric.
- Whether to commit `eval/runs/` or git-ignore it and keep only summaries.
