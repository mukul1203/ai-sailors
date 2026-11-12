"""A scripted model for the LLM ingestion stages: answers each stage from the prompt it gets."""

import json
import re

from storyquest.models.fake import FakeClient
from storyquest.models.llm import LLMError, Message

NARRATION = "The friends talk about what to do. Then something new happens in the jungle tonight."


def _between(prompt: str, tag: str) -> str:
    m = re.search(rf"<{tag}>\n(.*?)\n</{tag}>", prompt, re.DOTALL)
    return m.group(1) if m else ""


class StageLLM(FakeClient):
    """Segment: proposes every Nth paragraph. Beat: builds a valid answer from the scene.
    Entities: lists Mowgli plus one name that is not in the book. Set `mode` to break things."""

    def __init__(self, *, every: int = 12) -> None:
        self.every = every
        self.mode = "good"  # good, bad_quotes, garbage, down
        self.fail_after: int | None = None  # raise LLMError once this many calls were made
        super().__init__(self._respond)

    def calls_of(self, kind: str) -> int:
        return sum(1 for c in self.calls if self._kind(c) == kind)

    @staticmethod
    def _kind(messages: list[Message]) -> str:
        prompt = messages[0]["content"]
        if "Choose the paragraphs" in prompt:
            return "segment"
        if "You write for a story game" in prompt:
            return "beat"
        if "character guide" in prompt:
            return "entities"
        return "other"

    def _respond(self, messages: list[Message]) -> str:
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise LLMError("endpoint down")
        if self.mode == "down":
            raise LLMError("endpoint down")
        prompt = messages[0]["content"]
        kind = self._kind(messages)
        if self.mode == "garbage" and kind != "other":
            return "this is not json"
        if kind == "segment":
            first, last = (int(n) for n in re.findall(r"paragraphs (\d+) to (\d+)", prompt)[0])
            return json.dumps(
                {"starts": [n for n in range(first, last + 1) if n % self.every == 0]}
            )
        if kind == "beat":
            scene = " ".join(_between(prompt, "scene").split())
            words = [w for w in dict.fromkeys(re.findall(r"[A-Za-z]{5,}", scene))][:3]
            quote = scene[:70] if self.mode == "good" else "words that are not in the scene at all"
            return json.dumps(
                {
                    "title": "A Scene In The Jungle",
                    "narration_summary": NARRATION,
                    "clues": [{"quote": quote, "clue": f"Clue {i}"} for i in range(3)],
                    "vocabulary": words,
                    "choice_prompt": "What should they do next?",
                    "choice_options": ["Go on", "Wait here"],
                    "canon_option": 2,
                }
            )
        if kind == "entities":
            scene = _between(prompt, "passage")
            items = [
                {"name": "Zork Zorkson", "kind": "character", "aliases": [], "card": "Not real."}
            ]
            if "Mowgli" in scene:
                items.insert(
                    0,
                    {
                        "name": "Mowgli",
                        "kind": "character",
                        "aliases": ["Frog"],
                        "card": "A boy raised by wolves.",
                    },
                )
            return json.dumps({"entities": items})
        return "ok"
