"""Optional OpenTelemetry export of each turn, next to our own trace dashboard.

Off unless OTEL_EXPORTER_OTLP_ENDPOINT is set (for example http://localhost:4318, a local Jaeger).
Each turn becomes one trace: a `turn` span with one child span per model call (router, planner,
generate, critic) and per tool call. Model calls use the OpenTelemetry GenAI names
(`gen_ai.request.model`, `gen_ai.usage.input_tokens`, ...), so any OTLP viewer shows them.

By default no text leaves the app: spans carry the mode, route, flags, timings, tokens and models,
but not the child's message, the reply, prompts or tool arguments. OTEL_TRACE_TEXT=true adds the
message and the reply, for local debugging only. This matches TRACE_STORE=summary.

The turn is exported after it ends, from the timings the trace already records, so the agent code
does not change and a failing exporter can never break a turn.
"""

import atexit
import logging
import os
from collections.abc import Mapping
from typing import Any

from storyquest.agent.trace import StepTrace, ToolTrace, TurnResult

log = logging.getLogger(__name__)

Attributes = Mapping[str, str | int | float | bool | list[str]]

_tracer: Any = None
_ready = False


def enabled() -> bool:
    return bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")) and os.environ.get(
        "OTEL_SDK_DISABLED", ""
    ).lower() not in ("1", "true")


def _text_allowed() -> bool:
    return os.environ.get("OTEL_TRACE_TEXT", "").lower() in ("1", "true", "yes")


def _default_tracer() -> Any:
    """The tracer for the configured OTLP endpoint, set up once; None when export is off."""
    global _tracer, _ready
    if _ready:
        return _tracer
    _ready = True
    if not enabled():
        return None
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        log.warning(
            "OTEL_EXPORTER_OTLP_ENDPOINT is set but OpenTelemetry is not installed; "
            'run pip install -e ".[otel]". Traces stay on the dashboard only.'
        )
        return None
    service = os.environ.get("OTEL_SERVICE_NAME", "storyquest")
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))  # reads the endpoint
    atexit.register(provider.shutdown)  # send what is buffered when a CLI run ends
    _tracer = provider.get_tracer("storyquest")
    return _tracer


def _ns(seconds: float) -> int:
    return int(seconds * 1_000_000_000)


def _step_start(step: StepTrace | ToolTrace, turn_start: float) -> float:
    """A cached model call took no time now, whatever the original call took."""
    took = 0.0 if getattr(step, "cached", False) else step.latency_s
    return max(turn_start, step.ended_at - took)


def export_turn(
    result: TurnResult, attributes: Attributes | None = None, *, tracer: Any = None, text: str = ""
) -> None:
    """Send one finished turn as a trace. `text` is the child's message (sent only when
    OTEL_TRACE_TEXT is on). Never raises: tracing must not break a child's turn."""
    tracer = tracer or _default_tracer()
    if tracer is None or not result.started_at:
        return
    try:
        _export(tracer, result, attributes or {}, text)
    except Exception:  # an exporter bug or a bad value must not reach the child
        log.exception("could not export the turn to OpenTelemetry")


def _export(tracer: Any, result: TurnResult, attributes: Attributes, text: str) -> None:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode

    start = result.started_at
    end = start + result.total_latency_s
    attrs: dict[str, Any] = {
        "storyquest.mode": result.mode,
        "storyquest.route": result.route,
        "storyquest.flags": list(result.flags),
        "storyquest.model_calls": len(result.steps),
        "storyquest.tool_calls": len(result.tool_calls),
        "storyquest.passages": len(result.passages),
        "gen_ai.usage.input_tokens": result.prompt_tokens,
        "gen_ai.usage.output_tokens": result.completion_tokens,
        **{f"storyquest.seconds.{stage}": s for stage, s in result.timings.items()},
        **attributes,
    }
    if _text_allowed():
        attrs["storyquest.child_message"] = text
        attrs["storyquest.reply"] = result.reply
    root = tracer.start_span("turn", start_time=_ns(start), attributes=attrs)
    if result.route == "error":
        root.set_status(Status(StatusCode.ERROR, "the turn ended with an error reply"))
    parent = trace.set_span_in_context(root)

    for step in result.steps:
        span = tracer.start_span(
            step.name,
            context=parent,
            start_time=_ns(_step_start(step, start)),
            attributes={
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": step.model,
                "gen_ai.response.model": step.model,
                "gen_ai.usage.input_tokens": step.prompt_tokens,
                "gen_ai.usage.output_tokens": step.completion_tokens,
                "gen_ai.response.finish_reasons": [step.finish_reason or ""],
                "storyquest.cached": step.cached,
            },
        )
        span.end(end_time=_ns(max(step.ended_at, _step_start(step, start))))

    for call in result.tool_calls:
        span = tracer.start_span(
            f"tool {call.tool}",
            context=parent,
            start_time=_ns(_step_start(call, start)),
            attributes={
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": call.tool,
                "storyquest.tool.found": call.found,
                **({"storyquest.tool.argument": call.argument} if _text_allowed() else {}),
            },
        )
        if call.error:
            span.set_status(Status(StatusCode.ERROR, call.error))
        span.end(end_time=_ns(call.ended_at))

    root.end(end_time=_ns(max(end, start)))
