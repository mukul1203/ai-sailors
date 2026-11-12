# 07 — Evaluation Harness and Reports

Scope: running the live agent against the golden set in different modes and producing human-friendly reports. Items and scoring rules are defined in [../../eval/README.md](../../eval/README.md) and [../../eval/golden_v1.jsonl](../../eval/golden_v1.jsonl).

## Run model

```
storyquest eval run --modes "M0 M1 M1S" --split dev [--category SPO] [--no-judge] [--no-open]
storyquest eval report eval/runs/<time>
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

`make eval` runs every non-skipped item through each mode in `MODES` (default M0, M1, M1S), judges the replies, and saves `config.json`, `results.jsonl` and `summary.txt` per mode under `eval/runs/<time>/<mode>/`, plus one `report.html` for the whole batch, which it opens in the browser.

- **Skipped items:** those marked `skip` in the golden file need a full quest session (choice clicks, idle time, session cap) or an injected poisoned passage, so they wait for step 8.
- **Behaviour check:** answered, deflected, refused, asked to clarify or reassured, judged from the route and reply.
- **Forbidden words:** literal `must_not_include` entries are matched as whole words. A term the child used themselves may be repeated. Entries that describe content (for example "invented smells") are counted as unchecked.
- **Facts:** a keyword proxy at first. It misses correct answers that use different words, so it is only a lower bound until the judge has run.
- **LLM judge** (on by default; `--no-judge` skips it) reports three metrics, each in its own call: **recall** (how many expected facts the reply states), **faithfulness** (is every claim in the reply supported by the passages the model was given; the reply is split into claims, then each is checked against those passages only, never the book text) and **precision** (the share of claims that state an expected fact). Every "yes" must come with a quote, and code checks that at least 80% of the quote's words occur in the text it should come from (the reply for recall, the passages for claim support); a verdict without a real quote counts as "no". Pass needs recall of at least 0.5 and faithfulness of 100%; precision is reported but does not gate, because a longer reply that holds the required facts is still acceptable. Faithfulness is n/a in M0, which gets no passages. The judge is the same Qwen3-8B as the agent, so it is noisy. Use the numbers for comparing modes, and spot-check items in the report. Details: [10-scoring-reference.md](10-scoring-reference.md).
- **Scoring reference:** every rule, threshold and failure label that decides a result is in [10-scoring-reference.md](10-scoring-reference.md).
- **HTML report** (`make eval-report RUN=eval/runs/<time>` reopens one): a single self-contained page that explains each mode as numbered steps, compares the modes in one table (pass rate per category, search recall, facts, invention hint, cost, failure causes), has a legend for every term, and lists every question with the child's message, what a good agent should do, each mode's reply, the retrieved passages (with a tick on the one that holds the answer), the evidence the model chose, the judge's per-fact verdicts, and a plain-English reason for the result.
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
