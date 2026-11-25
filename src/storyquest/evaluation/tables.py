"""Report tables from saved eval runs, ready to paste into the technical report: headline
numbers per run, pass rates by question category, and failures by the brief's four classes."""

from collections.abc import Sequence
from statistics import mean
from typing import Any

from storyquest.evaluation.glossary import FAILURE_CLASSES, class_counts, recovered_tool_calls
from storyquest.evaluation.runner import fact_evidence_counts, faithfulness_counts, pass_rates

Run = tuple[dict[str, Any], list[dict[str, Any]]]


def _ratio(found: int, total: int) -> str:
    return f"{found}/{total} ({found / total:.0%})" if total else "n/a"


def headline_row(config: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    ran = [r for r in rows if not r["skipped"]]
    gold = [r for r in ran if r.get("retrieval_hit") is not None]
    facts = fact_evidence_counts(rows)
    faithful = faithfulness_counts(rows)

    def avg(key: str) -> float:
        return mean(r.get(key, 0) for r in ran) if ran else 0.0

    return [
        str(config["mode"]),
        str(config["split"]),
        _ratio(sum(bool(r["passed"]) for r in ran), len(ran)),
        _ratio(sum(bool(r["retrieval_hit"]) for r in gold), len(gold)),
        _ratio(*facts),
        _ratio(*faithful),
        f"{avg('calls'):.1f}",
        f"{avg('tool_calls'):.1f}",
        f"{avg('prompt_tokens'):.0f}",
        f"{avg('latency_s'):.1f}",
    ]


def render_tables(runs: Sequence[Run]) -> str:
    """Both tables for the given runs, in the order given."""
    head = [
        "Mode",
        "Split",
        "Pass rate (task completion)",
        "Gold passage found",
        "Facts' evidence found",
        "Faithful replies",
        "Model calls",
        "Tool calls",
        "Prompt tokens",
        "Seconds",
    ]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(headline_row(c, r)) + " |" for c, r in runs]

    rates = [pass_rates(rows) for _, rows in runs]
    categories = sorted({cat for r in rates for cat in r})
    names = [f"{c['mode']} {c['split']}" for c, _ in runs]
    lines += ["", "| Category | " + " | ".join(names) + " |", "|" + "---|" * (len(names) + 1)]
    for cat in categories:
        cells = [_ratio(*r[cat]) if cat in r else "" for r in rates]
        lines.append(f"| {cat} | " + " | ".join(cells) + " |")

    classes = [class_counts(rows) for _, rows in runs]
    lines += ["", "| Failure class | " + " | ".join(names) + " |", "|" + "---|" * (len(names) + 1)]
    for name in FAILURE_CLASSES:
        lines.append(f"| {name} | " + " | ".join(str(c[name]) for c in classes) + " |")
    recovered = [str(recovered_tool_calls(rows)) for _, rows in runs]
    lines.append("| Recovered tool-call problems (not failures) | " + " | ".join(recovered) + " |")

    sources = {f"{c.get('embedding_model') or 'none'}, {c['model']}" for c, _ in runs}
    lines += ["", "Embeddings and chat model: " + "; ".join(sorted(sources)) + "."]
    return "\n".join(lines)
