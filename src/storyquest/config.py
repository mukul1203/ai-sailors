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


def _trace_store(value: str) -> str:
    value = value.strip().lower()
    if value not in ("off", "summary", "full"):
        raise ValueError(f"TRACE_STORE must be off, summary or full, not {value!r}")
    return value


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
    reranker_provider: str
    reranker_model: str
    reranker_batch_size: int
    reranker_max_length: int
    embedding_provider: str
    embedding_model: str
    embedding_dim: int
    embedding_requests_per_minute: int
    embedding_ca_cert_path: Path
    embedding_batch_size: int
    embedding_max_chars: int
    embedding_context_chars: int
    embedding_query_prefix: str
    generation_max_tokens: int
    max_child_input_chars: int
    books_dirs: tuple[Path, ...]
    ingest_in_api: bool
    play_mode: str
    max_questions_per_session: int
    ask_min_interval_seconds: float
    api_debug: bool
    trace_store: str  # off | summary | full
    trace_dashboard: bool
    trace_retention_days: float
    data_dir: Path
    api_port: int
    dbviewer_port: int
    llm_base_url: str = field(repr=False)
    llm_api_key: str = field(repr=False)
    embedding_api_key: str = field(repr=False)
    embedding_base_url: str = field(repr=False)
    gemini_api_key: str = field(repr=False)
    session_secret: str = field(repr=False)
    admin_token: str = field(repr=False)


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
        short_chapter_chars=int(get("SHORT_CHAPTER_CHARS", "3500")),
        beat_target_chars=int(get("BEAT_TARGET_CHARS", "3500")),
        beat_min_chars=int(get("BEAT_MIN_CHARS", "1800")),
        beat_max_chars=int(get("BEAT_MAX_CHARS", "6500")),
        segment_window_paragraphs=int(get("SEGMENT_WINDOW_PARAGRAPHS", "60")),
        ingest_retries=int(get("INGEST_RETRIES", "2")),
        retrieval_top_k=int(get("RETRIEVAL_TOP_K", "6")),
        retrieval_candidates=int(get("RETRIEVAL_CANDIDATES", "20")),
        rrf_k=int(get("RRF_K", "60")),
        reranker_provider=get("RERANKER_PROVIDER", "none"),
        reranker_model=get("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"),
        reranker_batch_size=int(get("RERANKER_BATCH_SIZE", "32")),
        reranker_max_length=int(get("RERANKER_MAX_LENGTH", "512")),
        embedding_provider=get("EMBEDDING_PROVIDER", "gemini"),
        embedding_model=get("EMBEDDING_MODEL", "gemini-embedding-001"),
        embedding_dim=int(get("EMBEDDING_DIM", "768")),
        embedding_requests_per_minute=int(get("EMBEDDING_REQUESTS_PER_MINUTE", "30")),
        embedding_ca_cert_path=path(get("EMBEDDING_CA_CERT_PATH", "certs/vm02-ca.crt")),
        embedding_batch_size=int(get("EMBEDDING_BATCH_SIZE", "16")),
        embedding_max_chars=int(get("EMBEDDING_MAX_CHARS", "1600")),
        embedding_context_chars=int(get("EMBEDDING_CONTEXT_CHARS", "0")),
        embedding_query_prefix=get("EMBEDDING_QUERY_PREFIX"),
        generation_max_tokens=int(get("GENERATION_MAX_TOKENS", "200")),
        max_child_input_chars=int(get("MAX_CHILD_INPUT_CHARS", "300")),
        books_dirs=tuple(
            path(p.strip()) for p in get("BOOKS_DIR", "books,eval/books").split(",") if p.strip()
        ),
        ingest_in_api=_flag(get("INGEST_IN_API", "true")),
        play_mode=get("PLAY_MODE", "M2S"),
        max_questions_per_session=int(get("MAX_QUESTIONS_PER_SESSION", "10")),
        ask_min_interval_seconds=float(get("ASK_MIN_INTERVAL_SECONDS", "2")),
        api_debug=_flag(get("API_DEBUG", "false")),
        trace_store=_trace_store(get("TRACE_STORE", "summary")),
        trace_dashboard=_flag(get("TRACE_DASHBOARD", "false")),
        trace_retention_days=float(get("TRACE_RETENTION_DAYS", "30")),
        data_dir=path(get("DATA_DIR", "var")),
        api_port=int(get("API_PORT", "8000")),
        dbviewer_port=int(get("DBVIEWER_PORT", "8001")),
        llm_api_key=get("LLM_API_KEY"),
        embedding_api_key=get("EMBEDDING_API_KEY"),
        embedding_base_url=get("EMBEDDING_BASE_URL"),
        # Gemini reads GEMINI_API_KEY. The older EMBEDDING_API_KEY is accepted only while no
        # EMBEDDING_BASE_URL is set, so a key meant for another endpoint is never sent to Google.
        gemini_api_key=get("GEMINI_API_KEY")
        or ("" if get("EMBEDDING_BASE_URL") else get("EMBEDDING_API_KEY")),
        session_secret=get("SESSION_SECRET"),
        admin_token=get("ADMIN_TOKEN"),
    )
