import json
import re

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


def plan(question: str, *calls: tuple[str, str]) -> str:
    """A planner answer: the rewritten question and (tool, argument) pairs."""
    return json.dumps(
        {"question": question, "calls": [{"tool": t, "argument": a} for t, a in calls]}
    )


def verdict(v: str, problem: str = "") -> str:
    """A critic answer."""
    return json.dumps({"verdict": v, "problem": problem})


class AgentLLM(FakeClient):
    """Plays every model role of the agent loop: router, planner, answer and critic.

    Each role answers from its own list, one entry per call (the last entry repeats). An
    answer of None means "cite no evidence", which the grounding check refuses. `fail` names
    roles that raise LLMError instead.
    """

    def __init__(
        self,
        *,
        label: str = "story_question",
        plans: list[str] | None = None,
        answers: list[str | None] | None = None,
        verdicts: list[str] | None = None,
        fail: tuple[str, ...] = (),
    ) -> None:
        self.label = label
        self.script: dict[str, list[str | None]] = {
            "planner": list(plans or [plan("Why does Shere Khan limp?", ("search_book", "lame"))]),
            "generate": list(answers or ["Shere Khan was born lame in one foot."]),
            "critic": list(verdicts or [verdict("approve")]),
        }
        self.fail = fail
        self.roles: list[str] = []  # the role of every call, in order
        super().__init__(self._respond)

    @staticmethod
    def role(messages: list[Message]) -> str:
        system = messages[0]["content"]
        if "sort short messages" in system:
            return "router"
        if system.startswith("You plan how to answer"):
            return "planner"
        if system.startswith("You check an answer"):
            return "critic"
        return "generate"

    def chat(self, messages: list[Message], **kwargs: object) -> LLMResult:  # type: ignore[override]
        if self.role(messages) in self.fail:
            self.roles.append(self.role(messages))
            raise LLMError("endpoint down")
        return super().chat(messages, **kwargs)  # type: ignore[arg-type]

    def _respond(self, messages: list[Message]) -> str:
        role = self.role(messages)
        self.roles.append(role)
        if role == "router":
            return json.dumps({"label": self.label})
        queue = self.script[role]
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        if role != "generate":
            return str(reply)
        first_id = re.search(r"\[(\d+\.\d+)\]", messages[1]["content"])
        evidence = [first_id.group(1)] if reply is not None and first_id else []
        return json.dumps({"evidence": evidence, "answer": reply or "I don't know yet."})

    def prompts(self, role: str) -> list[str]:
        """The user message of every call to `role`, in order."""
        return [m[1]["content"] for m in self.calls if self.role(m) == role]


class FailingLLM:
    def chat(self, messages: list[Message], **kwargs: object) -> LLMResult:
        raise LLMError("endpoint down")
