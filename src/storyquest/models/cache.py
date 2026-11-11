"""Disk cache for deterministic (temperature 0) calls, keyed by the full request."""

import hashlib
import json
import os
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from storyquest.models.llm import LLMClient, LLMResult, Message


class CachedClient:
    def __init__(self, inner: LLMClient, cache_dir: Path, model: str) -> None:
        self._inner = inner
        self._dir = cache_dir
        self._model = model

    def chat(
        self,
        messages: list[Message],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        json_schema: dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> LLMResult:
        if temperature != 0:
            return self._inner.chat(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                json_schema=json_schema,
                extra_body=extra_body,
            )
        path = self._path(messages, max_tokens, json_schema, extra_body)
        if path.is_file():
            return replace(LLMResult(**json.loads(path.read_text())), cached=True)
        result = self._inner.chat(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            json_schema=json_schema,
            extra_body=extra_body,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(asdict(result)))
        tmp.replace(path)
        return result

    def _path(
        self,
        messages: list[Message],
        max_tokens: int,
        json_schema: dict[str, Any] | None,
        extra_body: dict[str, Any] | None,
    ) -> Path:
        key = json.dumps(
            [self._model, messages, max_tokens, json_schema, extra_body], sort_keys=True
        )
        digest = hashlib.sha256(key.encode()).hexdigest()
        return self._dir / digest[:2] / f"{digest}.json"
