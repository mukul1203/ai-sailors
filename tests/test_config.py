from pathlib import Path

from storyquest.config import load_settings


def write(path: Path, text: str) -> None:
    path.write_text(text)


def test_defaults_when_no_files(tmp_path: Path) -> None:
    s = load_settings(tmp_path, environ={})
    assert s.llm_max_concurrency == 1
    assert s.data_dir == tmp_path / "var"
    assert s.llm_api_key == ""


def test_precedence_config_then_dotenv_then_environment(tmp_path: Path) -> None:
    write(tmp_path / "config.env", "LLM_MODEL=from-config\nAPI_PORT=1111\nDATA_DIR=var\n")
    write(tmp_path / ".env", '# secrets\nLLM_API_KEY="abc"\nAPI_PORT=2222\n')
    s = load_settings(tmp_path, environ={"API_PORT": "3333"})
    assert s.llm_model == "from-config"
    assert s.llm_api_key == "abc"
    assert s.api_port == 3333


def test_absolute_paths_are_kept(tmp_path: Path) -> None:
    s = load_settings(tmp_path, environ={"DATA_DIR": "/data", "LLM_CA_CERT_PATH": "/certs/x.crt"})
    assert s.data_dir == Path("/data")
    assert s.llm_ca_cert_path == Path("/certs/x.crt")


def test_secrets_are_not_in_repr(tmp_path: Path) -> None:
    s = load_settings(
        tmp_path,
        environ={
            "LLM_API_KEY": "topsecret",
            "SESSION_SECRET": "hush",
            "LLM_BASE_URL": "https://10.0.0.1:1234/v1",
        },
    )
    text = repr(s)
    assert "topsecret" not in text
    assert "hush" not in text
    assert "10.0.0.1" not in text
