"""Build the configured LLM client and embedder from settings."""

from storyquest.config import Settings
from storyquest.models.cache import CachedClient
from storyquest.models.embedder import (
    CachedEmbedder,
    Embedder,
    EmbeddingError,
    FakeEmbedder,
    GeminiEmbedder,
    OpenAICompatibleEmbedder,
    QueryPrefixEmbedder,
)
from storyquest.models.fake import FakeClient
from storyquest.models.llm import LLMClient, LLMError
from storyquest.models.openai_compatible import OpenAICompatibleClient
from storyquest.models.throttle import ThrottledClient


def build_llm(settings: Settings, *, use_cache: bool = True) -> LLMClient:
    if settings.llm_provider == "fake":
        return FakeClient()
    if settings.llm_provider != "openai_compatible":
        raise LLMError(f"unknown LLM_PROVIDER {settings.llm_provider!r}")
    if not settings.llm_base_url or not settings.llm_api_key:
        raise LLMError("LLM_BASE_URL and LLM_API_KEY must be set in .env (see .env.example)")
    if not settings.llm_ca_cert_path.is_file():
        raise LLMError(f"CA certificate not found at {settings.llm_ca_cert_path}")

    client: LLMClient = ThrottledClient(
        OpenAICompatibleClient(
            settings.llm_base_url,
            settings.llm_api_key,
            settings.llm_model,
            settings.llm_ca_cert_path,
            timeout=settings.llm_timeout_seconds,
        ),
        max_concurrency=settings.llm_max_concurrency,
        requests_per_minute=settings.llm_requests_per_minute,
    )
    if use_cache:
        client = CachedClient(client, settings.data_dir / "cache" / "llm", settings.llm_model)
    return client


def build_embedder(settings: Settings, *, use_cache: bool = True) -> Embedder:
    if settings.embedding_provider == "fake":
        return FakeEmbedder(settings.embedding_dim)
    embedder: Embedder
    if settings.embedding_provider == "openai_compatible":
        if not settings.embedding_base_url or not settings.embedding_api_key:
            raise EmbeddingError(
                "Hybrid retrieval needs the embedding endpoint: set EMBEDDING_BASE_URL and "
                "EMBEDDING_API_KEY in .env (see .env.example)"
            )
        if not settings.embedding_ca_cert_path.is_file():
            raise EmbeddingError(
                f"Embedding CA certificate not found at {settings.embedding_ca_cert_path}"
            )
        embedder = OpenAICompatibleEmbedder(
            settings.embedding_base_url,
            settings.embedding_api_key,
            settings.embedding_model,
            settings.embedding_dim,
            settings.embedding_ca_cert_path,
            batch_size=settings.embedding_batch_size,
            max_chars=settings.embedding_max_chars,
            requests_per_minute=settings.embedding_requests_per_minute,
        )
    elif settings.embedding_provider == "gemini":
        if not settings.gemini_api_key:
            raise EmbeddingError(
                "Hybrid retrieval with Gemini needs a key: set GEMINI_API_KEY in .env "
                "(a Gemini API key from Google AI Studio)"
            )
        embedder = GeminiEmbedder(
            settings.gemini_api_key,
            settings.embedding_model,
            settings.embedding_dim,
            requests_per_minute=settings.embedding_requests_per_minute,
        )
    else:
        raise EmbeddingError(f"unknown EMBEDDING_PROVIDER {settings.embedding_provider!r}")
    if use_cache:
        embedder = CachedEmbedder(embedder, settings.data_dir / "cache" / "embeddings")
    if settings.embedding_query_prefix:
        embedder = QueryPrefixEmbedder(embedder, settings.embedding_query_prefix)
    return embedder
