from pathlib import Path

import certifi
import pytest

from storyquest.config import load_settings
from storyquest.models.build import build_embedder, build_llm
from storyquest.models.embedder import (
    CachedEmbedder,
    EmbeddingError,
    QueryPrefixEmbedder,
)
from storyquest.models.fake import FakeClient
from storyquest.models.llm import LLMError


def test_fake_provider(tmp_path: Path) -> None:
    settings = load_settings(tmp_path, environ={"LLM_PROVIDER": "fake"})
    assert isinstance(build_llm(settings), FakeClient)


def test_real_provider_needs_url_and_key(tmp_path: Path) -> None:
    settings = load_settings(tmp_path, environ={"LLM_PROVIDER": "openai_compatible"})
    with pytest.raises(LLMError, match="LLM_BASE_URL"):
        build_llm(settings)


def test_real_provider_needs_the_certificate_file(tmp_path: Path) -> None:
    env = {"LLM_BASE_URL": "https://h/v1", "LLM_API_KEY": "k"}
    with pytest.raises(LLMError, match="CA certificate"):
        build_llm(load_settings(tmp_path, environ=env))


def test_unknown_provider(tmp_path: Path) -> None:
    with pytest.raises(LLMError, match="unknown"):
        build_llm(load_settings(tmp_path, environ={"LLM_PROVIDER": "nope"}))


def openai_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    cert = tmp_path / "emb.crt"
    cert.write_text("not a real certificate")
    env = {
        "EMBEDDING_PROVIDER": "openai_compatible",
        "EMBEDDING_MODEL": "bge-small-en-v1.5",
        "EMBEDDING_DIM": "384",
        "EMBEDDING_BASE_URL": "https://h:1035/v1",
        "EMBEDDING_API_KEY": "k",
        "EMBEDDING_CA_CERT_PATH": str(cert),
    }
    env.update(extra)
    return env


def test_openai_embedder_needs_url_key_and_certificate(tmp_path: Path) -> None:
    env = openai_env(tmp_path)
    for missing, message in (
        ("EMBEDDING_BASE_URL", "EMBEDDING_BASE_URL"),
        ("EMBEDDING_API_KEY", "EMBEDDING_API_KEY"),
    ):
        partial = {k: v for k, v in env.items() if k != missing}
        with pytest.raises(EmbeddingError, match=message):
            build_embedder(load_settings(tmp_path, environ=partial))
    no_cert = {**env, "EMBEDDING_CA_CERT_PATH": str(tmp_path / "missing.crt")}
    with pytest.raises(EmbeddingError, match="certificate"):
        build_embedder(load_settings(tmp_path, environ=no_cert))


def test_openai_embedder_is_cached_and_prefixed_only_when_asked(tmp_path: Path) -> None:
    # Any loadable CA bundle works here; certifi's ships with httpx.
    real_bundle = {"EMBEDDING_CA_CERT_PATH": certifi.where()}
    plain = build_embedder(load_settings(tmp_path, environ=openai_env(tmp_path, **real_bundle)))
    assert isinstance(plain, CachedEmbedder)
    assert plain.model_id == "bge-small-en-v1.5:384" and plain.dim == 384

    env = openai_env(tmp_path, EMBEDDING_QUERY_PREFIX="Represent this sentence:", **real_bundle)
    prefixed = build_embedder(load_settings(tmp_path, environ=env))
    assert isinstance(prefixed, QueryPrefixEmbedder)
    assert prefixed.model_id == plain.model_id  # documents stay comparable across the two


def test_gemini_never_receives_a_key_meant_for_another_endpoint(tmp_path: Path) -> None:
    other = {"EMBEDDING_PROVIDER": "gemini", "EMBEDDING_API_KEY": "course-key"}
    legacy = load_settings(tmp_path, environ=other)
    assert legacy.gemini_api_key == "course-key"  # older setups: the key was for Gemini

    both = {**other, "EMBEDDING_BASE_URL": "https://h:1035/v1"}
    with pytest.raises(EmbeddingError, match="GEMINI_API_KEY"):
        build_embedder(load_settings(tmp_path, environ=both))

    named = {**both, "GEMINI_API_KEY": "g-key"}
    settings = load_settings(tmp_path, environ=named)
    assert settings.gemini_api_key == "g-key"
    assert isinstance(build_embedder(settings), CachedEmbedder)
