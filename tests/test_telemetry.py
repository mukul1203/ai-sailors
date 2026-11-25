"""OpenTelemetry export: one trace per turn, model and tool calls as child spans, no child text
unless asked for, and nothing at all when it is not configured."""

from collections.abc import Callable

import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from llm_helpers import AgentLLM, plan  # noqa: E402
from storyquest import telemetry  # noqa: E402
from storyquest.agent.context import AgentContext  # noqa: E402
from storyquest.agent.modes import get_mode  # noqa: E402
from storyquest.agent.trace import StepTrace, TurnResult  # noqa: E402
from storyquest.agent.turn import run_turn  # noqa: E402
from storyquest.domain.position import Position  # noqa: E402
from storyquest.models.llm import LLMClient  # noqa: E402

MakeCtx = Callable[[LLMClient], AgentContext]
QUESTION = "Why does Shere Khan limp? My name is Asha."


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    """Route the app's export to an in-memory exporter, as if an endpoint were configured."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "_tracer", provider.get_tracer("test"))
    monkeypatch.setattr(telemetry, "_ready", True)
    monkeypatch.delenv("OTEL_TRACE_TEXT", raising=False)
    return exporter


def _agent_turn(make_ctx: MakeCtx) -> TurnResult:
    llm = AgentLLM(plans=[plan("Why does Shere Khan limp?", ("search_book", "lame"))])
    return run_turn(make_ctx(llm), QUESTION, Position(0, 1), mode=get_mode("M5"))


@pytest.mark.integration
def test_an_agent_turn_becomes_one_trace_with_a_span_per_call(
    make_ctx: MakeCtx, spans: InMemorySpanExporter
) -> None:
    result = _agent_turn(make_ctx)
    by_name = {s.name: s for s in spans.get_finished_spans()}
    assert set(by_name) == {"turn", "router", "planner", "tool search_book", "generate", "critic"}
    root = by_name["turn"]
    assert root.parent is None
    assert root.attributes is not None
    assert root.attributes["storyquest.mode"] == "M5"
    assert root.attributes["storyquest.route"] == "story_question"
    assert root.attributes["storyquest.chapter"] == 0 and root.attributes["storyquest.beat"] == 1
    assert root.attributes["gen_ai.usage.input_tokens"] == result.prompt_tokens
    for name, span in by_name.items():
        if name != "turn":
            assert span.parent is not None and span.parent.span_id == root.context.span_id
            assert span.context.trace_id == root.context.trace_id
            assert root.start_time <= span.start_time <= span.end_time
    generate = by_name["generate"].attributes
    assert generate is not None and generate["gen_ai.operation.name"] == "chat"
    assert generate["gen_ai.request.model"] == "fake"
    tool = by_name["tool search_book"].attributes
    assert tool is not None and tool["gen_ai.tool.name"] == "search_book"


@pytest.mark.integration
def test_no_child_text_leaves_the_app_by_default(
    make_ctx: MakeCtx, spans: InMemorySpanExporter
) -> None:
    _agent_turn(make_ctx)
    values = [str(v) for s in spans.get_finished_spans() for v in (s.attributes or {}).values()]
    assert not any("Asha" in v or "limp" in v.lower() for v in values)


@pytest.mark.integration
def test_text_is_added_only_when_asked_for(
    make_ctx: MakeCtx, spans: InMemorySpanExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OTEL_TRACE_TEXT", "true")
    result = _agent_turn(make_ctx)
    (root,) = [s for s in spans.get_finished_spans() if s.name == "turn"]
    assert root.attributes is not None
    assert root.attributes["storyquest.child_message"] == QUESTION
    assert root.attributes["storyquest.reply"] == result.reply


def test_a_cached_call_takes_no_time_in_the_trace(spans: InMemorySpanExporter) -> None:
    step = StepTrace("generate", [], "{}", 10, 5, 3.0, True, "m", "stop", ended_at=100.5)
    turn = TurnResult("hi", "story_question", "M2S", [step], started_at=100.0, total_latency_s=1)
    telemetry.export_turn(turn)
    gen = next(s for s in spans.get_finished_spans() if s.name == "generate")
    assert gen.start_time == gen.end_time == 100_500_000_000


def test_nothing_is_exported_without_an_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.setattr(telemetry, "_tracer", None)
    monkeypatch.setattr(telemetry, "_ready", False)
    assert not telemetry.enabled() and telemetry._default_tracer() is None
    telemetry.export_turn(TurnResult("hi", "story_question", "M2S", started_at=1.0))


def test_a_broken_exporter_never_breaks_the_turn() -> None:
    class Broken:
        def start_span(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("collector down")

    turn = TurnResult("hi", "story_question", "M2S", started_at=1.0)
    telemetry.export_turn(turn, tracer=Broken())
