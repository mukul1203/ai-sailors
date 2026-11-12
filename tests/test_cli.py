from pathlib import Path

import pytest

from storyquest.cli import main


def test_config_command_hides_secrets(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "topsecret")
    monkeypatch.setenv("LLM_BASE_URL", "https://10.0.0.1:1234/v1")
    assert main(["config"]) == 0
    out = capsys.readouterr().out
    assert "llm_api_key set: True" in out
    assert "llm_base_url set: True" in out
    assert "topsecret" not in out
    assert "10.0.0.1" not in out


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "storyquest" in capsys.readouterr().out


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run the CLI in an empty folder with the fake model, so nothing real is touched."""
    monkeypatch.chdir(tmp_path)
    for key in ("DATA_DIR", "LLM_BASE_URL", "LLM_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    return Path(__file__).resolve().parent.parent / "eval"


@pytest.mark.integration
def test_the_ingestion_commands_end_to_end(
    cli_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    eval_dir = cli_env
    assert main(["catalog", "import", str(eval_dir / "books")]) == 0
    spine = str(eval_dir / "spine_mowgli_brothers.json")
    assert main(["ingest", "236", "--spine", spine]) == 0

    # The fake model answers "ok" to everything: unreadable, so the stages must degrade, not crash.
    assert main(["ingest", "236", "--stage", "llm", "--chapter", "2"]) == 0
    capsys.readouterr()
    assert main(["ingest-status", "236"]) == 0
    status = capsys.readouterr().out
    assert "ch2" in status and "segment" in status
    assert main(["review", "236", "--chapter", "2"]) == 0
    assert "generation failed" in capsys.readouterr().out
    assert main(["approve", "236", "--chapter", "2"]) == 0
    assert "have no generated content" in capsys.readouterr().out
    assert main(["publish", "236"]) == 1
    assert "not approved" in capsys.readouterr().err
    assert main(["entities", "236"]) == 0

    assert main(["ingest", "236", "--stage", "polish"]) == 1
    assert "Unknown stage" in capsys.readouterr().err
    assert main(["ingest", "236", "--stage", "llm", "--enqueue"]) == 0
    assert main(["worker", "--once"]) == 0
    assert "Handled 1 job" in capsys.readouterr().out
    assert main(["ingest", "999", "--enqueue"]) == 1
