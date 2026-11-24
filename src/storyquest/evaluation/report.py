"""Human-readable text reports for one run and for two runs side by side."""

from collections import Counter
from statistics import mean

from storyquest.evaluation.runner import (
    Row,
    fact_evidence_counts,
    faithfulness_counts,
    mean_precision,
    pass_rates,
)


def _pct(a: int, b: int) -> str:
    return f"{a}/{b} ({round(100 * a / b)}%)" if b else "n/a"


def summarize(config: Row, rows: list[Row]) -> str:
    ran = [r for r in rows if not r["skipped"]]
    skipped = [r for r in rows if r["skipped"]]
    passed = sum(bool(r["passed"]) for r in ran)
    out = [
        f"Run {config['mode']} | split {config['split']} | {len(ran)} run, {len(skipped)} skipped"
        f" | model {config['model']} | commit {config['git_commit']}"
        f"{' (uncommitted changes)' if config.get('git_dirty') else ''}",
        f"golden set {config['golden_sha256']} | book {config['book']} ({config['book_sha256']})"
        f" | top-k {config['retrieval_top_k']}",
    ]
    if config.get("embedding_model"):
        prefix = config.get("embedding_query_prefix")
        out.append(
            f"embeddings {config['embedding_model']}"
            + (f' | query prefix "{prefix}"' if prefix else " | no query prefix")
        )
    out += [
        "",
        f"Pass rate: {_pct(passed, len(ran))}",
    ]
    for cat, (p, n) in pass_rates(rows).items():
        out.append(f"  {cat}  {_pct(p, n)}")

    with_gold = [r for r in ran if r["retrieval_hit"] is not None]
    hits = sum(bool(r["retrieval_hit"]) for r in with_gold)
    out += [
        "",
        f"Retrieval: gold passage in the top {config['retrieval_top_k']} "
        f"for {_pct(hits, len(with_gold))}",
    ]
    found, total = fact_evidence_counts(ran)
    if total:
        out.append(
            f"Evidence recall: {found} of {total} expected facts had their evidence among the "
            f"top {config['retrieval_top_k']} passages"
        )
    routes = Counter(r["route"] for r in ran)
    out.append("Routes: " + ", ".join(f"{k} {v}" for k, v in routes.most_common()))
    coverage = [r["fact_coverage"] for r in ran if r["fact_coverage"] is not None]
    if coverage:
        how = "LLM judge" if config.get("judged") else "keyword proxy"
        out.append(f"Recall, fact coverage ({how}, answer items): mean {mean(coverage):.2f}")
    leaks = [r for r in ran if r["violations"]]
    ok, analysed = faithfulness_counts(ran)
    if analysed:
        out.append(
            f"Faithfulness: {ok} of {analysed} replies fully supported by their passages "
            "(100% required)"
        )
    precision = mean_precision(ran)
    if precision is not None:
        out.append(f"Precision (reported, not required): mean {precision:.2f}")
    out.append(f"Forbidden terms found in replies: {len(leaks)} items")
    if ran:
        out.append(
            f"Per item: {mean(r['calls'] for r in ran):.1f} model calls, "
            f"{mean(r.get('tool_calls', 0) for r in ran):.1f} tool calls, "
            f"{mean(r['prompt_tokens'] for r in ran):.0f} prompt + "
            f"{mean(r['completion_tokens'] for r in ran):.0f} completion tokens, "
            f"{mean(r['latency_s'] for r in ran):.1f}s"
        )

    labels = Counter(r["label"] for r in ran if not r["passed"])
    if labels:
        out += ["", "Failures by cause: " + ", ".join(f"{k} {v}" for k, v in labels.most_common())]
        out.append("")
        for r in ran:
            if r["passed"]:
                continue
            reply = " ".join(r["reply"].split())
            out += [
                f"  {r['id']} [{r['label']}] {r['position']} {r['input'][:70]!r}",
                f"      expected {r['expected']}; route {r['route']}; reply: {reply[:150]}",
                f"      retrieval_hit={r['retrieval_hit']} facts={r['fact_coverage']}"
                f" violations={r['violations']}",
            ]
    unchecked = sum(len(r["unchecked"]) for r in ran)
    if config.get("judged"):
        out += [
            "",
            f"Judged by {config['judge_model']}, the same model that wrote the replies, so expect "
            "some bias. Items the judge looked at are marked in results.jsonl.",
        ]
    else:
        out += [
            "",
            f"Not checked yet (needs the LLM judge): {unchecked} descriptive forbidden-content "
            "criteria, and whether replies state the must_include facts correctly.",
        ]
    if skipped:
        out.append("Skipped: " + ", ".join(f"{r['id']}" for r in skipped))
    return "\n".join(out)
