from pathlib import Path

from storyquest.models.cache import CachedClient
from storyquest.models.fake import FakeClient
from storyquest.models.llm import Message

MSG: list[Message] = [{"role": "user", "content": "hello"}]


def test_second_identical_call_is_served_from_disk(tmp_path: Path) -> None:
    fake = FakeClient("answer")
    client = CachedClient(fake, tmp_path, "m")
    first = client.chat(MSG, max_tokens=10)
    second = client.chat(MSG, max_tokens=10)
    assert (first.cached, second.cached) == (False, True)
    assert second.text == "answer"
    assert len(fake.calls) == 1


def test_any_change_to_the_request_misses_the_cache(tmp_path: Path) -> None:
    fake = FakeClient()
    client = CachedClient(fake, tmp_path, "m")
    client.chat(MSG, max_tokens=10)
    client.chat(MSG, max_tokens=11)
    client.chat([{"role": "user", "content": "other"}], max_tokens=10)
    client.chat(MSG, max_tokens=10, json_schema={"type": "object"})
    assert len(fake.calls) == 4


def test_cache_is_shared_across_instances_but_keyed_by_model(tmp_path: Path) -> None:
    CachedClient(FakeClient(), tmp_path, "m1").chat(MSG, max_tokens=10)
    fake = FakeClient()
    CachedClient(fake, tmp_path, "m1").chat(MSG, max_tokens=10)
    CachedClient(fake, tmp_path, "m2").chat(MSG, max_tokens=10)
    assert len(fake.calls) == 1


def test_nonzero_temperature_is_never_cached(tmp_path: Path) -> None:
    fake = FakeClient()
    client = CachedClient(fake, tmp_path, "m")
    client.chat(MSG, max_tokens=10, temperature=0.7)
    client.chat(MSG, max_tokens=10, temperature=0.7)
    assert len(fake.calls) == 2
    assert not list(tmp_path.rglob("*.json"))
