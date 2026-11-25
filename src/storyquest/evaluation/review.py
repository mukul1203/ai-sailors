"""Calibrating the judge against a person, once.

The judge is the same small model that writes the answers, so its verdicts are checked against a
person on a sample: every failed answer, plus a few passed ones (to catch answers the judge let
through). `eval review` writes the sample as a sheet; a person fills the `acceptable` column with
yes or no (is this a good answer for the child?); `eval calibrate` reads it back and reports how
often the judge agreed and the pass rate with the person's verdicts in place of the judge's.
Only the person's column counts: the `suggested` columns are a reading aid and are never scored.
"""

import csv
import random
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from storyquest.evaluation.glossary import explain, failure_class

Row = dict[str, Any]
Run = tuple[Row, list[Row]]

COLUMNS = [
    "mode",
    "split",
    "id",
    "category",
    "position",
    "question",
    "expected",
    "must_include",
    "reply",
    "cited_evidence",
    "judge",
    "why",
    "suggested",
    "suggested_reason",
    "acceptable",
    "note",
]
YES = {"yes", "y", "ok", "acceptable", "true", "1"}
NO = {"no", "n", "not acceptable", "false", "0"}


def sample(runs: Sequence[Run], passes_per_run: int = 8, seed: int = 0) -> list[Row]:
    """Every failed answer of each run, and `passes_per_run` passed ones chosen at random."""
    out: list[Row] = []
    for config, rows in runs:
        ran = [r for r in rows if not r["skipped"]]
        failed = [r for r in ran if not r["passed"]]
        passed = [r for r in ran if r["passed"]]
        rng = random.Random(f"{seed}:{config['mode']}:{config['split']}")
        chosen = rng.sample(passed, min(passes_per_run, len(passed)))
        for r in sorted(failed + chosen, key=lambda r: r["id"]):
            out.append(_sheet_row(config, r, int(config.get("retrieval_top_k", 6))))
    return out


def _sheet_row(config: Row, r: Row, top_k: int) -> Row:
    judge = "pass" if r["passed"] else f"FAIL ({failure_class(r['label'])}: {r['label']})"
    return {
        "mode": config["mode"],
        "split": config["split"],
        "id": r["id"],
        "category": r["category"],
        "position": r.get("position", ""),
        "question": r.get("input", ""),
        "expected": r.get("expected", ""),
        "must_include": " | ".join(r.get("must_include") or []),
        "reply": r.get("reply", ""),
        "cited_evidence": r.get("evidence", ""),
        "judge": judge,
        "why": " ".join(explain(r, top_k).split()),
        "suggested": "",
        "suggested_reason": "",
        "acceptable": "",
        "note": "",
    }


def write_sheet(rows: Sequence[Row], path: Path) -> None:
    """A CSV that opens in Excel or Google Sheets (UTF-8 with a byte-order mark)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def read_verdicts(path: Path) -> dict[tuple[str, str, str], bool]:
    """The person's verdicts: (mode, split, id) -> acceptable. Blank rows are not reviewed."""
    verdicts: dict[tuple[str, str, str], bool] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            value = (row.get("acceptable") or "").strip().lower()
            if value in YES:
                verdicts[(row["mode"], row["split"], row["id"])] = True
            elif value in NO:
                verdicts[(row["mode"], row["split"], row["id"])] = False
            elif value:
                raise ValueError(f"{row['id']} ({row['mode']}): acceptable must be yes or no")
    return verdicts


def calibrate(config: Row, rows: list[Row], verdicts: dict[tuple[str, str, str], bool]) -> Row:
    """How one run's judge compares with the person, and its pass rate with their verdicts."""
    ran = [r for r in rows if not r["skipped"]]
    key = (str(config["mode"]), str(config["split"]))
    reviewed = [(r, verdicts[(*key, r["id"])]) for r in ran if (*key, r["id"]) in verdicts]
    failed = [(r, ok) for r, ok in reviewed if not r["passed"]]
    passed = [(r, ok) for r, ok in reviewed if r["passed"]]
    return {
        "mode": config["mode"],
        "split": config["split"],
        "ran": len(ran),
        "judge_passed": sum(bool(r["passed"]) for r in ran),
        "reviewed": len(reviewed),
        "agreed": sum(bool(r["passed"]) == ok for r, ok in reviewed),
        "failures_reviewed": len(failed),
        "failures_overturned": sum(ok for _, ok in failed),
        "passes_reviewed": len(passed),
        "passes_overturned": sum(not ok for _, ok in passed),
        "unreviewed_failures": sum(1 for r in ran if not r["passed"]) - len(failed),
        "person_passed": sum(verdicts.get((*key, r["id"]), bool(r["passed"])) for r in ran),
    }


def render_calibration(runs: Sequence[Run], verdicts: dict[tuple[str, str, str], bool]) -> str:
    """The calibration table for the report."""
    stats = [calibrate(c, rows, verdicts) for c, rows in runs]
    stats = [s for s in stats if s["reviewed"]]
    if not stats:
        return "No reviewed rows match these runs."
    head = [
        "Mode",
        "Split",
        "Reviewed",
        "Judge agreed with the person",
        "Failures the person accepted",
        "Passes the person rejected",
        "Pass rate (judge)",
        "Pass rate (person-checked)",
    ]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for s in stats:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(s["mode"]),
                    str(s["split"]),
                    str(s["reviewed"]),
                    _ratio(s["agreed"], s["reviewed"]),
                    f"{s['failures_overturned']}/{s['failures_reviewed']}",
                    f"{s['passes_overturned']}/{s['passes_reviewed']}",
                    _ratio(s["judge_passed"], s["ran"]),
                    _ratio(s["person_passed"], s["ran"]),
                ]
            )
            + " |"
        )
    agreed = sum(s["agreed"] for s in stats)
    reviewed = sum(s["reviewed"] for s in stats)
    lines += [
        "",
        f"Overall the judge agreed with the person on {_ratio(agreed, reviewed)} of reviewed "
        "answers. Every failed answer and a random sample of passed ones were reviewed; a "
        "person-checked pass rate keeps the judge's verdict for answers nobody reviewed.",
    ]
    missing = sum(s["unreviewed_failures"] for s in stats)
    if missing:
        lines.append(f"{missing} failed answers have no verdict yet.")
    return "\n".join(lines)


def _ratio(found: int, total: int) -> str:
    return f"{found}/{total} ({found / total:.0%})" if total else "n/a"
