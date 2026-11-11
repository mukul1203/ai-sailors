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
