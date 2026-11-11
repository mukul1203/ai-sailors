import json
from collections.abc import Callable
from pathlib import Path

import pytest

from llm_helpers import ScriptedLLM
from storyquest.agent.context import AgentContext
from storyquest.agent.modes import get_mode
from storyquest.evaluation.items import load_items
from storyquest.evaluation.report import compare, summarize
from storyquest.evaluation.runner import load_run, make_config, pass_rates, run_eval, write_run
from storyquest.models.llm import LLMClient

pytestmark = pytest.mark.integration

IDS = {"CAN-003", "SPO-009", "SAF-002", "MAL-001", "FLO-001"}


def run(
    make_ctx: Callable[[LLMClient], AgentContext], eval_dir: Path, mode: str, llm: ScriptedLLM
) -> tuple[AgentContext, list[dict]]:  # type: ignore[type-arg]
    golden = eval_dir / "golden_v1.jsonl"
    items = [i for i in load_items(golden) if i.id in IDS]
    ctx = make_ctx(llm)
    return ctx, run_eval(ctx, items, get_mode(mode), log=lambda _: None)


def test_every_item_gets_a_row_and_skipped_ones_say_why(
    make_ctx: Callable[[LLMClient], AgentContext], eval_dir: Path
) -> None:
    _, rows = run(make_ctx, eval_dir, "M1", ScriptedLLM(answer="He is lame in one foot."))
    by_id = {r["id"]: r for r in rows}
    assert set(by_id) == IDS
    assert by_id["FLO-001"]["skipped"]
    assert "passed" not in by_id["FLO-001"]
    assert by_id["MAL-001"]["route"] == "empty" and by_id["MAL-001"]["passed"]
    assert by_id["CAN-003"]["retrieval_hit"] is True


def test_a_run_is_saved_and_can_be_reloaded_and_summarised(
    make_ctx: Callable[[LLMClient], AgentContext], eval_dir: Path, tmp_path: Path
) -> None:
    ctx, rows = run(make_ctx, eval_dir, "M1", ScriptedLLM(answer="He is lame in one foot."))
    config = make_config(ctx, get_mode("M1"), "dev", eval_dir / "golden_v1.jsonl", rows)
    summary = summarize(config, rows)
    run_dir = write_run(tmp_path / "runs", config, rows, summary)
    assert run_dir.name.startswith("M1-dev-")
    assert (run_dir / "summary.txt").read_text().startswith("Run M1 | split dev | 4 run, 1 skipped")
    loaded_config, loaded_rows = load_run(run_dir)
    assert loaded_config["mode"] == "M1" and loaded_rows == json.loads(json.dumps(rows))
    assert "Pass rate:" in summary and "Skipped: FLO-001" in summary
    assert sum(n for _, n in pass_rates(rows).values()) == 4


def test_compare_lists_what_changed_between_two_runs(
    make_ctx: Callable[[LLMClient], AgentContext], eval_dir: Path
) -> None:
    _, rows_a = run(make_ctx, eval_dir, "M1", ScriptedLLM(label="off_topic"))
    ctx, rows_b = run(make_ctx, eval_dir, "M1", ScriptedLLM(answer="He is lame in one foot."))
    config = make_config(ctx, get_mode("M1"), "dev", eval_dir / "golden_v1.jsonl", rows_b)
    text = compare((config, rows_a), (config, rows_b))
    assert "overall" in text
    assert "Pass in M1 but not in M1:" in text
    assert "CAN-003" in text  # fixed by answering instead of redirecting
