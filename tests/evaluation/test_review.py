"""Calibrating the judge: the sheet holds every failure and a sample of passes, only the
person's column is scored, and the agreement table counts both kinds of disagreement."""

import csv
from pathlib import Path

import pytest

from storyquest.evaluation.review import (
    calibrate,
    read_verdicts,
    render_calibration,
    sample,
    write_sheet,
)

CONFIG = {"mode": "M5", "split": "dev", "retrieval_top_k": 6}


def _row(i: int, passed: bool, label: str | None = None) -> dict[str, object]:
    return {
        "id": f"CAN-{i:03d}",
        "category": "CAN",
        "position": "B1",
        "input": f"question {i}",
        "expected": "answer",
        "must_include": ["a fact"],
        "reply": f"reply {i}",
        "evidence": "",
        "skipped": None,
        "passed": passed,
        "label": label,
        "route": "story_question",
        "flags": [],
        "violations": [],
        "behavior_ok": True,
        "fact_coverage": 1.0 if passed else 0.0,
    }


ROWS = [_row(i, True) for i in range(1, 11)] + [
    _row(11, False, "missing_facts"),
    _row(12, False, "unfaithful"),
    {**_row(13, False), "skipped": "flow item"},
]


def test_the_sheet_has_every_failure_and_a_fixed_sample_of_passes() -> None:
    rows = sample([(CONFIG, ROWS)], passes_per_run=3)
    ids = [r["id"] for r in rows]
    assert {"CAN-011", "CAN-012"} <= set(ids) and "CAN-013" not in ids
    assert sum(r["judge"] == "pass" for r in rows) == 3
    assert rows == sample([(CONFIG, ROWS)], passes_per_run=3)  # the same sample every time
    failed = next(r for r in rows if r["id"] == "CAN-011")
    assert failed["judge"].startswith("FAIL (Reasoning error: missing_facts)")
    assert failed["acceptable"] == "" and failed["why"]


def test_only_the_persons_column_is_read(tmp_path: Path) -> None:
    rows = sample([(CONFIG, ROWS)], passes_per_run=2)
    for r in rows:
        r["suggested"] = "yes"  # a suggestion is never a verdict
    by_id = {r["id"]: r for r in rows}
    by_id["CAN-011"]["acceptable"] = "Yes"
    by_id["CAN-012"]["acceptable"] = "no"
    path = tmp_path / "review.csv"
    write_sheet(rows, path)
    assert read_verdicts(path) == {("M5", "dev", "CAN-011"): True, ("M5", "dev", "CAN-012"): False}


def test_a_value_other_than_yes_or_no_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "review.csv"
    rows = sample([(CONFIG, ROWS)], passes_per_run=0)
    rows[0]["acceptable"] = "maybe"
    write_sheet(rows, path)
    with pytest.raises(ValueError, match="yes or no"):
        read_verdicts(path)


def test_agreement_counts_overturned_failures_and_passes() -> None:
    verdicts = {
        ("M5", "dev", "CAN-011"): True,  # the judge failed a good answer
        ("M5", "dev", "CAN-012"): False,  # the judge was right
        ("M5", "dev", "CAN-001"): False,  # the judge passed a bad answer
        ("M5", "dev", "CAN-002"): True,
    }
    s = calibrate(CONFIG, ROWS, verdicts)
    assert s["ran"] == 12 and s["judge_passed"] == 10
    assert s["reviewed"] == 4 and s["agreed"] == 2
    assert (s["failures_overturned"], s["passes_overturned"]) == (1, 1)
    assert s["person_passed"] == 10  # +1 accepted failure, -1 rejected pass
    table = render_calibration([(CONFIG, ROWS)], verdicts)
    assert "| M5 | dev | 4 | 2/4 (50%) | 1/2 | 1/2 | 10/12 (83%) | 10/12 (83%) |" in table


def test_the_sheet_opens_as_plain_csv(tmp_path: Path) -> None:
    path = tmp_path / "review.csv"
    write_sheet(sample([(CONFIG, ROWS)], passes_per_run=1), path)
    with path.open(encoding="utf-8-sig") as f:
        header = next(csv.reader(f))
    assert header[:3] == ["mode", "split", "id"] and "acceptable" in header
