import json
from collections.abc import Callable
from pathlib import Path

import pytest

from llm_helpers import ScriptedLLM
from storyquest.agent.context import AgentContext
from storyquest.agent.modes import get_mode
from storyquest.evaluation.html_report import render_report
from storyquest.evaluation.items import load_items
from storyquest.evaluation.runner import judge_rows, make_config, run_eval
from storyquest.models.fake import FakeClient
from storyquest.models.llm import LLMClient, Message

pytestmark = pytest.mark.integration

IDS = {"CAN-003", "OOC-001", "SAF-002", "FLO-001"}


class JudgingLLM(ScriptedLLM):
    """Router and answer as ScriptedLLM; the judge's three calls answer from fixed replies."""

    def __init__(
        self,
        verdict: dict[str, object],
        claims: list[str] | None = None,
        verify: dict[str, object] | None = None,
        **kw: str,
    ) -> None:
        self.verdict, self.claims, self.verify = verdict, claims or [], verify or {}
        super().__init__(**kw)
        self._reply = self._respond_all

    def _respond_all(self, messages: list[Message]) -> str:
        prompt = messages[0]["content"]
        if "List the separate factual claims" in prompt:
            return json.dumps({"claims": self.claims})
        if "Check each numbered claim" in prompt:
            return json.dumps(self.verify)
        if "strict grader" in prompt:
            return json.dumps(self.verdict)
        return self._respond(messages)


SUPPORTED = {
    "claim_1_quote": "lame in one foot",
    "claim_1_supported": True,
    "claim_1_fact": 1,
}


def prepare(
    make_ctx: Callable[[LLMClient], AgentContext], eval_dir: Path, llm: FakeClient, mode: str = "M1"
):  # type: ignore[no-untyped-def]
    items = [i for i in load_items(eval_dir / "golden_v1.jsonl") if i.id in IDS]
    ctx = make_ctx(llm)
    rows = run_eval(ctx, items, get_mode(mode), log=lambda _: None)
    return ctx, {i.id: i for i in items}, rows


def test_a_good_verdict_turns_a_keyword_miss_into_a_pass(make_ctx, eval_dir) -> None:  # type: ignore[no-untyped-def]
    llm = JudgingLLM(
        {
            "fact_1_quote": "He has a bad foot",
            "fact_1": True,
            "fact_2_quote": "called him the lame one",
            "fact_2": True,
            "forbidden_1_quote": "",
            "forbidden_1": False,
        },
        claims=["Shere Khan is lame in one foot."],
        verify=SUPPORTED,
        answer="He has a bad foot, and his mother called him the lame one.",
    )
    ctx, items, rows = prepare(make_ctx, eval_dir, llm)
    judged = {r["id"]: r for r in judge_rows(ctx, items, rows, log=lambda _: None)}
    can3 = judged["CAN-003"]
    assert can3["judge"]["facts"] == [True, True] and can3["fact_coverage"] == 1.0
    assert can3["faithfulness"] == 1.0 and can3["precision"] == 1.0
    assert "fact_coverage_proxy" in can3 and can3["passed"]
    assert "judge" not in judged["FLO-001"]  # skipped items are never judged
    assert judged["SAF-002"]["judge"]["forbidden_found"] == []  # descriptive rule, judged clean

    golden = eval_dir / "golden_v1.jsonl"
    page = render_report(
        [(make_config(ctx, get_mode("M1"), "dev", golden, rows), list(judged.values()))]
    )
    assert "Claims in the reply, checked against the passages" in page
    assert "Faithfulness: 1 of 1 claims supported" in page and "Precision" in page


def test_one_unsupported_claim_fails_the_item(make_ctx, eval_dir) -> None:  # type: ignore[no-untyped-def]
    llm = JudgingLLM(
        {
            "fact_1_quote": "lame in one foot",
            "fact_1": True,
            "fact_2_quote": "lame in one foot",
            "fact_2": True,
            "forbidden_1_quote": "",
            "forbidden_1": False,
        },
        claims=["He is lame in one foot.", "He is also a wolf."],
        verify={
            **SUPPORTED,
            "claim_2_quote": "",
            "claim_2_supported": False,
            "claim_2_fact": 0,
        },
        answer="He is lame in one foot and a wolf.",
    )
    ctx, items, rows = prepare(make_ctx, eval_dir, llm)
    can3 = {r["id"]: r for r in judge_rows(ctx, items, rows, log=lambda _: None)}["CAN-003"]
    assert can3["faithfulness"] == 0.5
    assert not can3["passed"] and can3["label"] == "unfaithful"


def test_faithfulness_is_not_checked_when_the_model_got_no_passages(make_ctx, eval_dir) -> None:  # type: ignore[no-untyped-def]
    llm = JudgingLLM(
        {"fact_1_quote": "lame", "fact_1": True, "fact_2_quote": "lame", "fact_2": True},
        answer="He is lame.",
    )
    ctx, items, rows = prepare(make_ctx, eval_dir, llm, mode="M0")
    can3 = {r["id"]: r for r in judge_rows(ctx, items, rows, log=lambda _: None)}["CAN-003"]
    assert can3["faithfulness"] is None and can3["judge"]["claims"] is None
    assert can3["passed"]


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


def test_the_report_escapes_replies_and_explains_each_mode_and_item(make_ctx, eval_dir) -> None:  # type: ignore[no-untyped-def]
    golden = eval_dir / "golden_v1.jsonl"
    runs = []
    for name, answer in (
        ("M0", "<script>alert(1)</script>"),
        ("M1", "He is lame in one foot."),
        ("M1S", "He is lame in one foot."),
    ):
        ctx, _, rows = prepare(make_ctx, eval_dir, ScriptedLLM(answer=answer))
        mode = get_mode(name)
        rows = run_eval(
            ctx, [i for i in load_items(golden) if i.id in IDS], mode, log=lambda _: None
        )
        runs.append((make_config(ctx, mode, "dev", golden, rows), rows))
    page = render_report(runs)
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    assert "Plain model, no book" in page and "Retrieval + sentence evidence" in page
    assert "Legend" in page and "BM25 score" in page and "Passages retrieved" in page
    assert "How the agent got here" in page and "CAN-003" in page and "modes differ" in page
    assert "This mode does not search the book" in page  # the M0 panel
    assert "Skipped (1)" in page
