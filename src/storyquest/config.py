"""Settings: config.env (committed) < .env (secrets) < real environment variables."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("\"'")
    return values


@dataclass(frozen=True)
class Settings:
    root: Path
    llm_provider: str
    llm_model: str
    llm_ca_cert_path: Path
    llm_max_concurrency: int
    llm_requests_per_minute: int
    llm_timeout_seconds: float
    chunk_target_chars: int
    chunk_max_chars: int
    short_chapter_chars: int
    retrieval_top_k: int
    generation_max_tokens: int
    max_child_input_chars: int
    data_dir: Path
    api_port: int
    dbviewer_port: int
    llm_base_url: str = field(repr=False)
    llm_api_key: str = field(repr=False)
    session_secret: str = field(repr=False)


def load_settings(root: Path | None = None, environ: Mapping[str, str] | None = None) -> Settings:
    root = (root or Path.cwd()).resolve()
    merged: dict[str, str] = {}
    merged.update(_parse_env_file(root / "config.env"))
    merged.update(_parse_env_file(root / ".env"))
    merged.update(os.environ if environ is None else environ)

    def get(key: str, default: str = "") -> str:
        return merged.get(key, default)

    def path(value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else root / p

    return Settings(
        root=root,
        llm_provider=get("LLM_PROVIDER", "openai_compatible"),
        llm_base_url=get("LLM_BASE_URL"),
        llm_model=get("LLM_MODEL", "Qwen/Qwen3-8B"),
        llm_ca_cert_path=path(get("LLM_CA_CERT_PATH", "certs/ca.crt")),
        llm_max_concurrency=int(get("LLM_MAX_CONCURRENCY", "1")),
        llm_requests_per_minute=int(get("LLM_REQUESTS_PER_MINUTE", "50")),
        llm_timeout_seconds=float(get("LLM_TIMEOUT_SECONDS", "120")),
        chunk_target_chars=int(get("CHUNK_TARGET_CHARS", "1200")),
        chunk_max_chars=int(get("CHUNK_MAX_CHARS", "1800")),
        short_chapter_chars=int(get("SHORT_CHAPTER_CHARS", "8000")),
        retrieval_top_k=int(get("RETRIEVAL_TOP_K", "3")),
        generation_max_tokens=int(get("GENERATION_MAX_TOKENS", "200")),
        max_child_input_chars=int(get("MAX_CHILD_INPUT_CHARS", "300")),
        data_dir=path(get("DATA_DIR", "var")),
        api_port=int(get("API_PORT", "8000")),
        dbviewer_port=int(get("DBVIEWER_PORT", "8001")),
        llm_api_key=get("LLM_API_KEY"),
        session_secret=get("SESSION_SECRET"),
    )
