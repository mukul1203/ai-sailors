from pathlib import Path

import pytest

from storyquest.config import load_settings
from storyquest.models.build import build_llm
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
