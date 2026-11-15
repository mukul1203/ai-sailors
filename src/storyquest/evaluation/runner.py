"""Running the golden set through the agent and writing the results."""

import dataclasses
import hashlib
import json
import subprocess
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from storyquest.agent.context import AgentContext
from storyquest.agent.modes import MODES, Mode
from storyquest.agent.replies import REPLIES
from storyquest.agent.retrieval import retrieve
from storyquest.agent.turn import run_turn
from storyquest.evaluation.items import GoldItem
from storyquest.evaluation.judge import evidence_text, judge_item, needs_judging
from storyquest.evaluation.scoring import decide, score_item
from storyquest.ingestion.pipeline import load_cleaned
from storyquest.ingestion.text import Cleaned
from storyquest.stores.search import SearchHit

Row = dict[str, Any]


def _overlaps(cleaned: Cleaned, ranges: list[tuple[int, int]], hit: SearchHit) -> bool:
    if hit.source != "chunk":
        return False  # entity cards are not book text, so they never hold the gold lines
    first, last = cleaned.line_at(hit.start_char), cleaned.line_at(hit.end_char - 1)
    return any(first <= b and a <= last for a, b in ranges)


def _hit_has_gold(cleaned: Cleaned, item: GoldItem, hit: SearchHit) -> bool:
    return _overlaps(cleaned, item.gold_lines, hit)


def _plain_hits(ctx: AgentContext, item: GoldItem, mode: Mode) -> list[SearchHit]:
    return retrieve(ctx, mode, item.input, item.position)[0]


def _retrieval_hit(ctx: AgentContext, cleaned: Cleaned, item: GoldItem, mode: Mode) -> bool | None:
    """Did the mode's search put the gold lines in the top passages? Independent of the model."""
    if not item.gold_lines or not item.input.strip():
        return None
    return any(_hit_has_gold(cleaned, item, h) for h in _plain_hits(ctx, item, mode))


def _facts_found(
    ctx: AgentContext, cleaned: Cleaned, item: GoldItem, mode: Mode
) -> list[bool] | None:
    """For each expected fact, did the mode's search find a passage that holds its evidence?"""
    if not item.fact_lines or not item.input.strip():
        return None
    hits = _plain_hits(ctx, item, mode)
    return [any(_overlaps(cleaned, ranges, h) for h in hits) for ranges in item.fact_lines]


def run_item(ctx: AgentContext, cleaned: Cleaned, item: GoldItem, mode: Mode) -> Row:
    row: Row = {
        "id": item.id,
        "category": item.category,
        "split": item.split,
        "chapter": item.position.chapter_idx,
        "position": f"B{item.position.beat_idx + 1}",
        "input": item.input[:200],
        "expected": item.expected_behavior,
        "must_include": item.must_include,
        "fact_evidence": item.fact_evidence,
        "must_not_include": item.must_not_include,
        "skipped": item.skip,
    }
    if item.skip:
        return row
    result = run_turn(ctx, item.input, item.position, mode=mode)
    score = score_item(item, result, _retrieval_hit(ctx, cleaned, item, mode))
    row.update(
        route=result.route,
        reply=result.reply,
        flags=result.flags,
        behavior_ok=score.behavior_ok,
        violations=score.violations,
        unchecked=score.unchecked,
        fact_coverage=score.fact_coverage,
        retrieval_hit=score.retrieval_hit,
        fact_found=_facts_found(ctx, cleaned, item, mode),
        passed=score.passed,
        label=score.label,
        calls=len(result.steps),
        prompt_tokens=sum(s.prompt_tokens for s in result.steps),
        completion_tokens=sum(s.completion_tokens for s in result.steps),
        latency_s=round(sum(s.latency_s for s in result.steps), 2),
        passages=[
            {
                "chapter": p.chapter_idx,
                "beat": p.beat_idx,
                "idx": p.idx,
                "score": round(p.score, 2),
                "text": p.text,
                "has_gold": _hit_has_gold(cleaned, item, p),
                "bm25_rank": p.bm25_rank,
                "dense_rank": p.dense_rank,
                "source": p.source,
            }
            for p in result.passages
        ],
        evidence=result.evidence,
        gold_text=evidence_text(item, cleaned),
    )
    return row


def run_eval(
    ctx: AgentContext, items: list[GoldItem], mode: Mode, *, log: Callable[[str], None]
) -> list[Row]:
    cleaned = load_cleaned(ctx.settings.data_dir, ctx.book)
    rows = []
    for n, item in enumerate(items, 1):
        row = run_item(ctx, cleaned, item, mode)
        verdict = (
            "skip" if row["skipped"] else ("pass" if row["passed"] else f"FAIL {row['label']}")
        )
        log(f"[{n}/{len(items)}] {item.id:8} {verdict}")
        rows.append(row)
    return rows


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _git_dirty() -> bool | None:
    """True when tracked files have uncommitted changes, so a result is not tied to the commit."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            check=True,
        )
        return bool(out.stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        return None


def make_config(
    ctx: AgentContext, mode: Mode, split: str, golden_path: Path, rows: list[Row]
) -> Row:
    s = ctx.settings
    return {
        "mode": mode.name,
        "split": split,
        "model": s.llm_model,
        "book": ctx.book.id,
        "book_sha256": ctx.book.content_sha256[:12],
        "golden_sha256": hashlib.sha256(golden_path.read_bytes()).hexdigest()[:12],
        "golden_path": str(golden_path),
        "judged": False,
        "git_commit": _git_commit(),
        "git_dirty": _git_dirty(),
        "retrieval_top_k": s.retrieval_top_k,
        # Which vectors a hybrid run searched, so two embedding models can be told apart later.
        "embedding_model": (
            ctx.embedder.model_id if mode.hybrid and ctx.embedder is not None else None
        ),
        "embedding_query_prefix": s.embedding_query_prefix if mode.hybrid else None,
        "generation_max_tokens": s.generation_max_tokens,
        "items": len(rows),
        "started": datetime.now().isoformat(timespec="seconds"),
    }


def new_batch_dir(root: Path) -> Path:
    """One folder per `eval run`, holding a sub-folder per mode and the combined report."""
    return root / datetime.now().strftime("%Y%m%d-%H%M%S")


def write_run(batch_dir: Path, config: Row, rows: list[Row], summary: str) -> Path:
    run_dir = batch_dir / str(config["mode"])
    save_run(run_dir, config, rows, summary)
    return run_dir


def save_run(run_dir: Path, config: Row, rows: list[Row], summary: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    (run_dir / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (run_dir / "summary.txt").write_text(summary + "\n")


def judge_rows(
    ctx: AgentContext,
    items: dict[str, GoldItem],
    rows: list[Row],
    *,
    log: Callable[[str], None],
) -> list[Row]:
    """Add the LLM judge's verdict to rows that need it and recompute pass or fail.

    Rows that used passages are also checked for faithfulness: every claim in a model-written
    reply must be supported by those passages, or the item fails.
    """
    out: list[Row] = []
    for row in rows:
        item = items.get(row["id"])
        if row["skipped"] or item is None:
            out.append(row)
            continue
        passages = [p["text"] for p in row.get("passages", []) if p.get("text")]
        written = row["reply"] not in REPLIES.values()
        if not (needs_judging(item, row["unchecked"]) or (passages and written)):
            out.append(row)
            continue
        verdict = judge_item(
            ctx.llm, item, row["reply"], passages if written else [], row["unchecked"]
        )
        if verdict is None:
            log(f"judged {item.id:8} judge answer unreadable, keeping the keyword check")
            out.append({**row, "judge_error": "the judge's answer was not valid JSON"})
            continue
        facts = verdict.facts_stated
        coverage = sum(facts) / len(facts) if facts else row["fact_coverage"]
        faithfulness = verdict.faithfulness
        passed, label = decide(
            item,
            row["route"],
            row["behavior_ok"],
            [*row["violations"], *verdict.forbidden_found],
            coverage,
            faithfulness is not None and faithfulness < 1.0,
            row["retrieval_hit"],
        )
        log(f"judged {item.id:8} {'pass' if passed else f'FAIL {label}'}")
        out.append(
            {
                **row,
                "fact_coverage_proxy": row.get("fact_coverage_proxy", row["fact_coverage"]),
                "fact_coverage": coverage,
                "faithfulness": faithfulness,
                "precision": verdict.precision,
                "judge": {
                    "facts": facts,
                    "fact_details": [
                        {
                            "fact": f,
                            "stated": s,
                            "quote": q,
                            "judge_said_yes": y,
                            "quote_ok": ok,
                        }
                        for f, s, q, y, ok in zip(
                            item.must_include,
                            facts,
                            verdict.fact_quotes,
                            verdict.fact_said,
                            verdict.fact_quote_ok,
                            strict=False,
                        )
                    ],
                    "forbidden_found": verdict.forbidden_found,
                    "claims": None
                    if verdict.claims is None
                    else [dataclasses.asdict(c) for c in verdict.claims],
                    "prompt": verdict.prompt,
                    "raw": verdict.raw,
                    "claims_prompt": verdict.claims_prompt,
                    "claims_raw": verdict.claims_raw,
                    "verify_prompt": verdict.verify_prompt,
                    "verify_raw": verdict.verify_raw,
                },
                "passed": passed,
                "label": label,
            }
        )
    return out


def load_run(run_dir: Path) -> tuple[Row, list[Row]]:
    config: Row = json.loads((run_dir / "config.json").read_text())
    rows = [json.loads(line) for line in (run_dir / "results.jsonl").read_text().splitlines()]
    return config, rows


def load_batch(path: Path) -> list[tuple[Row, list[Row]]]:
    """Loads one run folder, or every mode folder inside a batch folder (in mode order)."""
    if (path / "results.jsonl").exists():
        return [load_run(path)]
    runs = [load_run(d) for d in sorted(path.iterdir()) if (d / "results.jsonl").exists()]
    if not runs:
        raise FileNotFoundError(f"No evaluation results found in {path}")
    return sorted(runs, key=lambda r: list(MODES).index(r[0]["mode"]))


def fact_evidence_counts(rows: list[Row]) -> tuple[int, int]:
    """(expected facts whose evidence plain retrieval found, facts that have evidence lines)."""
    flags = [f for r in rows if not r["skipped"] for f in (r.get("fact_found") or [])]
    return sum(flags), len(flags)


def faithfulness_counts(rows: list[Row]) -> tuple[int, int]:
    """(replies fully supported by their passages, replies that were analysed)."""
    done = [r for r in rows if not r["skipped"] and r.get("faithfulness") is not None]
    return sum(r["faithfulness"] >= 1.0 for r in done), len(done)


def mean_precision(rows: list[Row]) -> float | None:
    values = [r["precision"] for r in rows if not r["skipped"] and r.get("precision") is not None]
    return sum(values) / len(values) if values else None


CATEGORY_ORDER = ["CAN", "CHR", "SPO", "OOC", "DIS", "FLO", "SAF", "INJ", "PII", "MAL"]


def pass_rates(rows: list[Row]) -> dict[str, tuple[int, int]]:
    """Category -> (passed, run) for the items that were actually run."""
    totals: Counter[str] = Counter()
    passed: Counter[str] = Counter()
    for r in rows:
        if r["skipped"]:
            continue
        totals[r["category"]] += 1
        passed[r["category"]] += bool(r["passed"])
    return {c: (passed[c], totals[c]) for c in CATEGORY_ORDER if totals[c]}
