import json
from collections.abc import Callable
from pathlib import Path

import pytest

from llm_helpers import ScriptedLLM
from storyquest.agent.context import AgentContext
from storyquest.agent.modes import get_mode
from storyquest.evaluation.html_report import render_html
from storyquest.evaluation.items import load_items
from storyquest.evaluation.runner import judge_rows, make_config, run_eval
from storyquest.models.fake import FakeClient
from storyquest.models.llm import LLMClient, Message

pytestmark = pytest.mark.integration

IDS = {"CAN-003", "OOC-001", "SAF-002", "FLO-001"}


class JudgingLLM(ScriptedLLM):
    """Router and answer as ScriptedLLM; the judge answers from a fixed verdict."""

    def __init__(self, verdict: dict[str, object], **kw: str) -> None:
        self.verdict = verdict
        super().__init__(**kw)
        self._reply = self._respond_all

    def _respond_all(self, messages: list[Message]) -> str:
        if "strict grader" in messages[0]["content"]:
            return json.dumps(self.verdict)
        return self._respond(messages)


def prepare(make_ctx: Callable[[LLMClient], AgentContext], eval_dir: Path, llm: FakeClient):  # type: ignore[no-untyped-def]
    items = [i for i in load_items(eval_dir / "golden_v1.jsonl") if i.id in IDS]
    ctx = make_ctx(llm)
    rows = run_eval(ctx, items, get_mode("M1"), log=lambda _: None)
    return ctx, {i.id: i for i in items}, rows


def test_a_good_verdict_turns_a_keyword_miss_into_a_pass(make_ctx, eval_dir) -> None:  # type: ignore[no-untyped-def]
    llm = JudgingLLM(
        {
            "contradicts_book_quote": "",
            "contradicts_book": False,
            "fact_1_quote": "He has a bad foot",
            "fact_1": True,
            "fact_2_quote": "called him the lame one",
            "fact_2": True,
            "forbidden_1_quote": "",
            "forbidden_1": False,
        },
        answer="He has a bad foot, and his mother called him the lame one.",
    )
    ctx, items, rows = prepare(make_ctx, eval_dir, llm)
    judged = {r["id"]: r for r in judge_rows(ctx, items, rows, log=lambda _: None)}
    can3 = judged["CAN-003"]
    assert can3["judge"]["facts"] == [True, True] and can3["fact_coverage"] == 1.0
    assert "fact_coverage_proxy" in can3 and can3["passed"]
    assert "judge" not in judged["FLO-001"]  # skipped items are never judged
    assert judged["SAF-002"]["judge"]["forbidden_found"] == []  # descriptive rule, judged clean


def test_a_contradiction_is_recorded_but_does_not_fail_the_item(make_ctx, eval_dir) -> None:  # type: ignore[no-untyped-def]
    llm = JudgingLLM(
        {
            "contradicts_book_quote": "and a wolf",
            "contradicts_book": True,
            "fact_1_quote": "lame in one foot",
            "fact_1": True,
            "fact_2_quote": "lame in one foot",
            "fact_2": True,
            "forbidden_1_quote": "",
            "forbidden_1": False,
        },
        answer="He is lame in one foot and a wolf.",
    )
    ctx, items, rows = prepare(make_ctx, eval_dir, llm)
    judged = {r["id"]: r for r in judge_rows(ctx, items, rows, log=lambda _: None)}
    assert judged["CAN-003"]["passed"]
    assert judged["CAN-003"]["judge"]["contradicts_book"]


def test_descriptive_forbidden_content_found_by_the_judge_fails_the_item(
    make_ctx, eval_dir
) -> None:  # type: ignore[no-untyped-def]
    llm = JudgingLLM(
        {"forbidden_1_quote": "color is blue", "forbidden_1": True},
        answer="His color is blue.",
    )
    ctx, items, rows = prepare(make_ctx, eval_dir, llm)
    judged = {r["id"]: r for r in judge_rows(ctx, items, rows, log=lambda _: None)}
    assert judged["OOC-001"]["judge"]["forbidden_found"] == ["any specific color"]
    assert not judged["OOC-001"]["passed"]


def test_the_html_report_escapes_replies_and_shows_the_baseline(make_ctx, eval_dir) -> None:  # type: ignore[no-untyped-def]
    ctx, _, rows = prepare(make_ctx, eval_dir, ScriptedLLM(answer="<script>alert(1)</script>"))
    config = make_config(ctx, get_mode("M1"), "dev", eval_dir / "golden_v1.jsonl", rows)
    page = render_html(config, rows)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
    assert "CAN-003" in page and "By category" in page and "Skipped (1)" in page
    base_config = {**config, "mode": "M0"}
    page2 = render_html(config, rows, (base_config, rows))
    assert "M0 baseline" in page2 and "+0 pts" in page2
