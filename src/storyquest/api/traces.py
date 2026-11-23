"""The admin trace dashboard's read API, mounted at /api/admin/traces.

Traces hold children's questions, so the whole thing is off unless TRACE_DASHBOARD is on
(a 404 otherwise, as if it did not exist) and then needs the ADMIN_TOKEN in the X-Admin-Token
header. This is a stop-gap until the app has real accounts.
"""

import secrets
import sqlite3
from collections.abc import Callable, Iterator
from typing import Any

from fastapi import APIRouter, Depends, Header, Query

from storyquest.agent.modes import describe_steps, get_mode
from storyquest.api.play import PlayError
from storyquest.config import Settings
from storyquest.evaluation.glossary import explain_flag
from storyquest.stores.traces import TraceFilter, get_trace, list_traces, trace_stats


def _filter(
    mode: str = "",
    route: str = "",
    flag: str = "",
    since: float | None = None,
    until: float | None = None,
    min_latency: float | None = Query(None, ge=0),
    cached: bool | None = None,
) -> TraceFilter:
    return TraceFilter(mode, route, flag, since, until, min_latency, cached)


def _explain(trace: dict[str, Any], top_k: int) -> dict[str, Any]:
    """Plain-language notes for the flags and the steps of this trace's mode."""
    inner = trace["trace"]
    notes: dict[str, Any] = {"flags": {f: explain_flag(f) for f in inner["flags"]}, "pipeline": []}
    try:
        notes["pipeline"] = describe_steps(get_mode(inner["mode"]), top_k)
    except ValueError:  # a mode that has since been removed
        pass
    return notes


def build_router(
    settings: Settings, app_conn: Callable[[], Iterator[sqlite3.Connection]]
) -> APIRouter:
    def gate(x_admin_token: str = Header("")) -> None:
        if not settings.trace_dashboard:
            raise PlayError(404, "not_found", "Not found.")
        # an unset ADMIN_TOKEN means nobody gets in, rather than everybody
        if not settings.admin_token or not secrets.compare_digest(
            x_admin_token.encode(), settings.admin_token.encode()
        ):
            raise PlayError(401, "unauthorized", "The admin token is missing or wrong.")

    router = APIRouter(prefix="/api/admin/traces", dependencies=[Depends(gate)])
    App = Depends(app_conn)
    Filter = Depends(_filter)

    @router.get("")
    def traces(
        f: TraceFilter = Filter,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        app: sqlite3.Connection = App,
    ) -> dict[str, Any]:
        return list_traces(app, f, limit=limit, offset=offset)

    @router.get("/stats")
    def stats(f: TraceFilter = Filter, app: sqlite3.Connection = App) -> dict[str, Any]:
        return trace_stats(app, f)

    @router.get("/{trace_id}")
    def one(trace_id: int, app: sqlite3.Connection = App) -> dict[str, Any]:
        trace = get_trace(app, trace_id)
        if trace is None:
            raise PlayError(404, "no_such_trace", "No such trace.")
        return {**trace, "notes": _explain(trace, settings.retrieval_top_k)}

    return router
