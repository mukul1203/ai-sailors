"""Running the golden set through the agent and writing the results."""

import hashlib
import json
import subprocess
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from storyquest.agent.context import AgentContext
from storyquest.agent.modes import Mode
from storyquest.agent.turn import run_turn
from storyquest.evaluation.items import GoldItem
from storyquest.evaluation.scoring import score_item
from storyquest.ingestion.pipeline import load_cleaned
from storyquest.ingestion.text import Cleaned
from storyquest.stores.search import search_chunks

Row = dict[str, Any]


def _retrieval_hit(ctx: AgentContext, cleaned: Cleaned, item: GoldItem) -> bool | None:
    """Did plain retrieval put the gold lines in the top passages? Independent of the model."""
    if not item.gold_lines or not item.input.strip():
        return None
    hits = search_chunks(
        ctx.conn, ctx.book.id, item.input, item.position, limit=ctx.settings.retrieval_top_k
    )
    for h in hits:
        first, last = cleaned.line_at(h.start_char), cleaned.line_at(h.end_char - 1)
        if any(first <= b and a <= last for a, b in item.gold_lines):
            return True
    return False


def run_item(ctx: AgentContext, cleaned: Cleaned, item: GoldItem, mode: Mode) -> Row:
    row: Row = {
        "id": item.id,
        "category": item.category,
        "split": item.split,
        "position": f"B{item.position.beat_idx + 1}",
        "input": item.input[:200],
        "expected": item.expected_behavior,
        "skipped": item.skip,
    }
    if item.skip:
        return row
    result = run_turn(ctx, item.input, item.position, mode=mode)
    score = score_item(item, result, _retrieval_hit(ctx, cleaned, item))
    row.update(
        route=result.route,
        reply=result.reply,
        flags=result.flags,
        behavior_ok=score.behavior_ok,
        violations=score.violations,
        unchecked=score.unchecked,
        fact_coverage=score.fact_coverage,
        retrieval_hit=score.retrieval_hit,
        passed=score.passed,
        label=score.label,
        calls=len(result.steps),
        prompt_tokens=sum(s.prompt_tokens for s in result.steps),
        completion_tokens=sum(s.completion_tokens for s in result.steps),
        latency_s=round(sum(s.latency_s for s in result.steps), 2),
        passages=[
            {"chapter": p.chapter_idx, "beat": p.beat_idx, "idx": p.idx, "score": round(p.score, 2)}
            for p in result.passages
        ],
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
        "git_commit": _git_commit(),
        "retrieval_top_k": s.retrieval_top_k,
        "generation_max_tokens": s.generation_max_tokens,
        "items": len(rows),
        "started": datetime.now().isoformat(timespec="seconds"),
    }


def write_run(root: Path, config: Row, rows: list[Row], summary: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = root / f"{config['mode']}-{config['split']}-{stamp}"
    run_dir.mkdir(parents=True)
    (run_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    (run_dir / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (run_dir / "summary.txt").write_text(summary + "\n")
    return run_dir


def load_run(run_dir: Path) -> tuple[Row, list[Row]]:
    config: Row = json.loads((run_dir / "config.json").read_text())
    rows = [json.loads(line) for line in (run_dir / "results.jsonl").read_text().splitlines()]
    return config, rows


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
