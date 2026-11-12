"""Build the configured LLM client and embedder from settings."""

from storyquest.config import Settings
from storyquest.models.cache import CachedClient
from storyquest.models.embedder import (
    CachedEmbedder,
    Embedder,
    EmbeddingError,
    FakeEmbedder,
    GeminiEmbedder,
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
    if settings.embedding_provider != "gemini":
        raise EmbeddingError(f"unknown EMBEDDING_PROVIDER {settings.embedding_provider!r}")
    if not settings.embedding_api_key:
        raise EmbeddingError(
            "Hybrid retrieval needs an embedding key: set EMBEDDING_API_KEY in .env "
            "(a Gemini API key from Google AI Studio)"
        )
    embedder: Embedder = GeminiEmbedder(
        settings.embedding_api_key,
        settings.embedding_model,
        settings.embedding_dim,
        requests_per_minute=settings.embedding_requests_per_minute,
    )
    if use_cache:
        embedder = CachedEmbedder(embedder, settings.data_dir / "cache" / "embeddings")
    return embedder
