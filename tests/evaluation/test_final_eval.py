"""The pieces of `make final-eval`: the preflight check and the report tables."""

from pathlib import Path

import pytest

from storyquest.cli import main
from storyquest.evaluation.tables import render_tables


@pytest.fixture
def empty_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    for key in ("DATA_DIR", "LLM_BASE_URL", "LLM_API_KEY", "EMBEDDING_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    return tmp_path


def test_preflight_passes_when_both_models_answer(
    empty_folder: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    assert main(["eval", "preflight"]) == 0
    out = capsys.readouterr().out
    assert "ok       chat model" in out and "ok       embeddings" in out


def test_preflight_fails_and_says_which_model_is_missing(
    empty_folder: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")  # with no URL or key set
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    assert main(["eval", "preflight"]) == 1
    assert "FAILED   chat model" in capsys.readouterr().err


def run(mode: str, split: str, passed: list[bool]) -> tuple[dict, list[dict]]:  # type: ignore[type-arg]
    config = {"mode": mode, "split": split, "model": "Qwen/Qwen3-8B", "embedding_model": "bge:384"}
    rows = [
        {
            "skipped": None,
            "category": "CAN" if n % 2 else "SAF",
            "passed": ok,
            "label": None if ok else "retrieval_miss",
            "flags": ["tool_error"] if n == 0 else [],
            "retrieval_hit": ok if n % 2 else None,
            "fact_found": [ok],
            "faithfulness": 1.0 if ok else 0.5,
            "calls": 2,
            "tool_calls": 1,
            "prompt_tokens": 1000,
            "latency_s": 1.5,
        }
        for n, ok in enumerate(passed)
    ]
    rows.append({"skipped": "needs a session", "category": "FLO"})
    return config, rows


def test_the_tables_give_headline_numbers_and_categories() -> None:
    text = render_tables([run("M2S", "dev", [True, True, False, True])])
    assert (
        "| M2S | dev | 3/4 (75%) | 2/2 (100%) | 3/4 (75%) | 3/4 (75%) | 2.0 | 1.0 | 1000 | 1.5 |"
        in text
    )
    assert "| CAN | 2/2 (100%) |" in text and "| SAF | 1/2 (50%) |" in text
    assert "FLO" not in text  # skipped items are not scored
    assert "| Retrieval miss | 1 |" in text and "| Hallucination | 0 |" in text
    assert "| Recovered tool-call problems (not failures) | 1 |" in text
    assert text.endswith("Embeddings and chat model: bge:384, Qwen/Qwen3-8B.")


def test_every_failure_label_belongs_to_one_of_the_briefs_four_classes() -> None:
    from storyquest.evaluation.glossary import CLASS_OF, FAILURE_CAUSES, FAILURE_CLASSES

    assert set(CLASS_OF) == set(FAILURE_CAUSES)
    assert list(FAILURE_CLASSES) == [
        "Retrieval miss",
        "Reasoning error",
        "Tool-call error",
        "Hallucination",
    ]
    labels = [label for group in FAILURE_CLASSES.values() for label in group]
    assert len(labels) == len(set(labels))  # no label in two classes
