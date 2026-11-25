"""Saving and reading turn traces (the `turn_traces` table in app.db). No HTTP in here."""

import json
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

from storyquest.agent.trace import TurnResult


@dataclass(frozen=True)
class TraceFilter:
    mode: str = ""
    route: str = ""
    flag: str = ""  # a flag name; "ungrounded" also matches "ungrounded:no_evidence"
    since: float | None = None
    until: float | None = None
    min_latency: float | None = None
    cached: bool | None = None
    otel_trace: str = ""  # an OpenTelemetry trace id, or its start (Jaeger shows 7 digits)


def save_trace(
    app: sqlite3.Connection, session_id: str, event_id: int | None, result: TurnResult, store: str
) -> None:
    """Write one trace row. `store` is "summary" or "full" (the caller skips "off")."""
    app.execute(
        "INSERT INTO turn_traces (session_id, event_id, created_at, mode, route, stored,"
        " total_latency_s, prompt_tokens, completion_tokens, any_cached, flags, trace)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            event_id,
            result.started_at or time.time(),
            result.mode,
            result.route,
            store,
            result.total_latency_s,
            result.prompt_tokens,
            result.completion_tokens,
            int(any(s.cached for s in result.steps)),
            json.dumps(result.flags),
            json.dumps(result.to_dict(full=store == "full")),
        ),
    )


def prune_traces(app: sqlite3.Connection, older_than_days: float) -> int:
    """Delete traces (not the sessions) older than this many days. Returns how many."""
    cutoff = time.time() - older_than_days * 86400
    return app.execute("DELETE FROM turn_traces WHERE created_at < ?", (cutoff,)).rowcount


def _where(f: TraceFilter) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    if f.mode:
        clauses.append("t.mode = ?")
        args.append(f.mode)
    if f.route:
        clauses.append("t.route = ?")
        args.append(f.route)
    if f.flag:
        clauses.append(
            "EXISTS (SELECT 1 FROM json_each(t.flags) WHERE value = ? OR value LIKE ? ESCAPE '\\')"
        )
        escaped = f.flag.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        args += [f.flag, f"{escaped}:%"]
    if f.since is not None:
        clauses.append("t.created_at >= ?")
        args.append(f.since)
    if f.until is not None:
        clauses.append("t.created_at < ?")
        args.append(f.until)
    if f.min_latency is not None:
        clauses.append("t.total_latency_s >= ?")
        args.append(f.min_latency)
    if f.cached is not None:
        clauses.append("t.any_cached = ?")
        args.append(int(f.cached))
    otel = f.otel_trace.strip().lower()
    if otel:
        if not all(c in "0123456789abcdef" for c in otel):
            otel = "-"  # not a trace id: match nothing
        clauses.append("json_extract(t.trace, '$.otel_trace_id') LIKE ?")
        args.append(f"{otel}%")
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", args


_SUMMARY_COLUMNS = (
    "t.id, t.session_id, t.created_at, t.mode, t.route, t.stored, t.total_latency_s,"
    " t.prompt_tokens, t.completion_tokens, t.any_cached, t.flags, e.text AS question"
)
_FROM = " FROM turn_traces t LEFT JOIN session_events e ON e.id = t.event_id"


def list_traces(
    app: sqlite3.Connection, f: TraceFilter, *, limit: int = 50, offset: int = 0
) -> dict[str, Any]:
    where, args = _where(f)
    total = app.execute(f"SELECT COUNT(*){_FROM}{where}", args).fetchone()[0]
    rows = app.execute(
        f"SELECT {_SUMMARY_COLUMNS}{_FROM}{where} ORDER BY t.created_at DESC, t.id DESC"
        " LIMIT ? OFFSET ?",
        [*args, limit, offset],
    ).fetchall()
    items = [
        {
            "id": r["id"],
            "session_id": r["session_id"],
            "created_at": r["created_at"],
            "mode": r["mode"],
            "route": r["route"],
            "stored": r["stored"],
            "question": r["question"] or "",
            "total_latency_s": r["total_latency_s"],
            "prompt_tokens": r["prompt_tokens"],
            "completion_tokens": r["completion_tokens"],
            "cached": bool(r["any_cached"]),
            "flags": json.loads(r["flags"]),
        }
        for r in rows
    ]
    return {"items": items, "total": total}


def get_trace(app: sqlite3.Connection, trace_id: int) -> dict[str, Any] | None:
    r = app.execute(
        f"SELECT {_SUMMARY_COLUMNS}, e.reply AS reply, t.trace AS trace{_FROM} WHERE t.id = ?",
        (trace_id,),
    ).fetchone()
    if r is None:
        return None
    return {
        "id": r["id"],
        "session_id": r["session_id"],
        "created_at": r["created_at"],
        "stored": r["stored"],
        "question": r["question"] or "",
        "reply": r["reply"] or "",
        "prompt_tokens": r["prompt_tokens"],
        "completion_tokens": r["completion_tokens"],
        "cached": bool(r["any_cached"]),
        "trace": json.loads(r["trace"]),
    }


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))] if ordered else 0.0


def trace_stats(app: sqlite3.Connection, f: TraceFilter) -> dict[str, Any]:
    where, args = _where(f)
    rows = app.execute(
        f"SELECT t.route, t.total_latency_s, t.prompt_tokens, t.completion_tokens, t.flags{_FROM}"
        f"{where}",
        args,
    ).fetchall()
    n = len(rows)
    latencies = [r["total_latency_s"] for r in rows]
    flag_counts: Counter[str] = Counter()
    story = misses = 0
    for r in rows:
        flags = json.loads(r["flags"])
        flag_counts.update({fl.partition(":")[0] for fl in flags})
        if r["route"] == "story_question":
            story += 1
        if "no_hits" in flags:
            misses += 1
    return {
        "total": n,
        "by_route": dict(Counter(r["route"] for r in rows).most_common()),
        "latency_mean_s": round(sum(latencies) / n, 3) if n else 0.0,
        "latency_p95_s": round(_p95(latencies), 3),
        "tokens_per_turn": (
            round(sum(r["prompt_tokens"] + r["completion_tokens"] for r in rows) / n, 1)
            if n
            else 0.0
        ),
        "top_flags": [{"flag": k, "count": v} for k, v in flag_counts.most_common(8)],
        # of the story questions, how many found no passage the child may see
        "retrieval_miss_rate": round(misses / story, 3) if story else 0.0,
    }
