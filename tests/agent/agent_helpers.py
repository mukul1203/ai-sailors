import json

from storyquest.models.fake import FakeClient
from storyquest.models.llm import LLMError, LLMResult, Message


class ScriptedLLM(FakeClient):
    """Answers the router with a fixed label and everything else with a fixed answer."""

    def __init__(self, label: str = "story_question", answer: str = "Shere Khan is lame.") -> None:
        self.label = label
        self.answer = answer
        super().__init__(self._respond)

    def _respond(self, messages: list[Message]) -> str:
        if "sort short messages" in messages[0]["content"]:
            return json.dumps({"label": self.label})
        return self.answer

    @property
    def generation_calls(self) -> list[list[Message]]:
        return [m for m in self.calls if "sort short messages" not in m[0]["content"]]


class FailingLLM:
    def chat(self, messages: list[Message], **kwargs: object) -> LLMResult:
        raise LLMError("endpoint down")
