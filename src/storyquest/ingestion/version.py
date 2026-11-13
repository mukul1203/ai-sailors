"""The pipeline version: a short hash of everything that changes what the LLM stages produce."""

import hashlib
import json

from storyquest.config import Settings
from storyquest.ingestion.prompts import load_prompt


def pipeline_version(settings: Settings) -> str:
    parts = [
        settings.llm_model,
        settings.beat_target_chars,
        settings.beat_min_chars,
        settings.beat_max_chars,
        settings.segment_window_paragraphs,
        settings.chunk_target_chars,
        settings.chunk_max_chars,
        *(
            load_prompt(name)
            for name in ("segment", "beat", "question", "entities", "safety_terms")
        ),
    ]
    return "v" + hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:8]
