"""Build the configured LLM client from settings."""

from storyquest.config import Settings
from storyquest.models.cache import CachedClient
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
        ),
        max_concurrency=settings.llm_max_concurrency,
        requests_per_minute=settings.llm_requests_per_minute,
    )
    if use_cache:
        client = CachedClient(client, settings.data_dir / "cache" / "llm", settings.llm_model)
    return client
