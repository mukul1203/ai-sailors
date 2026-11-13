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


def _flag(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


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
    beat_target_chars: int
    beat_min_chars: int
    beat_max_chars: int
    segment_window_paragraphs: int
    ingest_retries: int
    retrieval_top_k: int
    retrieval_candidates: int
    rrf_k: int
    embedding_provider: str
    embedding_model: str
    embedding_dim: int
    embedding_requests_per_minute: int
    generation_max_tokens: int
    max_child_input_chars: int
    play_mode: str
    play_unpublished: bool
    max_questions_per_session: int
    ask_min_interval_seconds: float
    api_debug: bool
    data_dir: Path
    api_port: int
    dbviewer_port: int
    llm_base_url: str = field(repr=False)
    llm_api_key: str = field(repr=False)
    embedding_api_key: str = field(repr=False)
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
        chunk_target_chars=int(get("CHUNK_TARGET_CHARS", "500")),
        chunk_max_chars=int(get("CHUNK_MAX_CHARS", "1800")),
        short_chapter_chars=int(get("SHORT_CHAPTER_CHARS", "8000")),
        beat_target_chars=int(get("BEAT_TARGET_CHARS", "6000")),
        beat_min_chars=int(get("BEAT_MIN_CHARS", "2500")),
        beat_max_chars=int(get("BEAT_MAX_CHARS", "11000")),
        segment_window_paragraphs=int(get("SEGMENT_WINDOW_PARAGRAPHS", "60")),
        ingest_retries=int(get("INGEST_RETRIES", "2")),
        retrieval_top_k=int(get("RETRIEVAL_TOP_K", "6")),
        retrieval_candidates=int(get("RETRIEVAL_CANDIDATES", "20")),
        rrf_k=int(get("RRF_K", "60")),
        embedding_provider=get("EMBEDDING_PROVIDER", "gemini"),
        embedding_model=get("EMBEDDING_MODEL", "gemini-embedding-001"),
        embedding_dim=int(get("EMBEDDING_DIM", "768")),
        embedding_requests_per_minute=int(get("EMBEDDING_REQUESTS_PER_MINUTE", "30")),
        generation_max_tokens=int(get("GENERATION_MAX_TOKENS", "200")),
        max_child_input_chars=int(get("MAX_CHILD_INPUT_CHARS", "300")),
        play_mode=get("PLAY_MODE", "M2S"),
        play_unpublished=_flag(get("PLAY_UNPUBLISHED", "false")),
        max_questions_per_session=int(get("MAX_QUESTIONS_PER_SESSION", "10")),
        ask_min_interval_seconds=float(get("ASK_MIN_INTERVAL_SECONDS", "2")),
        api_debug=_flag(get("API_DEBUG", "false")),
        data_dir=path(get("DATA_DIR", "var")),
        api_port=int(get("API_PORT", "8000")),
        dbviewer_port=int(get("DBVIEWER_PORT", "8001")),
        llm_api_key=get("LLM_API_KEY"),
        embedding_api_key=get("EMBEDDING_API_KEY") or get("GEMINI_API_KEY"),
        session_secret=get("SESSION_SECRET"),
    )
