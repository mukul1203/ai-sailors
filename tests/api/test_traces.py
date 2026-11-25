# ruff: noqa: F811  (the `seeded` fixture is imported, then used as a test argument)
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_api import BOOK, CHAPTER, make_settings, publish, seeded, start  # noqa: F401

from llm_helpers import ScriptedLLM
from storyquest.api import play
from storyquest.api.main import create_app
from storyquest.api.play import purge_sessions
from storyquest.config import Settings
from storyquest.stores.db import connect
from storyquest.stores.traces import prune_traces

pytestmark = pytest.mark.integration

TOKEN = "s3cret"
AUTH = {"X-Admin-Token": TOKEN}


def make_client(
    tmp_path: Path,
    seeded: Settings,
    label: str = "story_question",
    **env: str,
) -> tuple[TestClient, Settings]:
    publish(seeded)
    settings = make_settings(tmp_path, **{"TRACE_DASHBOARD": "true", "ADMIN_TOKEN": TOKEN, **env})
    llm = ScriptedLLM(label=label, answer="Shere Khan is lame.")
    return TestClient(create_app(settings, llm=llm)), settings


def ask(client: TestClient, sid: str, text: str = "Why does Shere Khan limp?") -> None:
    r = client.post(f"/api/sessions/{sid}/ask", json={"text": text})
    assert r.status_code == 200, r.text


def test_the_dashboard_is_hidden_unless_switched_on(tmp_path: Path, seeded: Settings) -> None:
    publish(seeded)
    client = TestClient(create_app(make_settings(tmp_path, ADMIN_TOKEN=TOKEN), llm=ScriptedLLM()))
    assert client.get("/api/admin/traces", headers=AUTH).status_code == 404
    assert client.get("/api/health").json()["traces"] is False


def test_it_needs_the_admin_token(tmp_path: Path, seeded: Settings) -> None:
    client, _ = make_client(tmp_path, seeded)
    assert client.get("/api/admin/traces").status_code == 401
    assert client.get("/api/admin/traces", headers={"X-Admin-Token": "nope"}).status_code == 401
    assert client.get("/api/admin/traces", headers=AUTH).status_code == 200


def test_with_no_token_configured_nobody_gets_in(tmp_path: Path, seeded: Settings) -> None:
    client, _ = make_client(tmp_path, seeded, ADMIN_TOKEN="")
    assert client.get("/api/admin/traces", headers={"X-Admin-Token": ""}).status_code == 401


def test_an_asked_question_is_traced_with_timings_and_steps(
    tmp_path: Path,
    seeded: Settings,
) -> None:
    client, _ = make_client(tmp_path, seeded)
    ask(client, start(client)["id"])
    listing = client.get("/api/admin/traces", headers=AUTH).json()
    assert listing["total"] == 1
    row = listing["items"][0]
    assert row["route"] == "story_question" and row["question"] == "Why does Shere Khan limp?"
    assert row["total_latency_s"] > 0 and row["stored"] == "summary"

    detail = client.get(f"/api/admin/traces/{row['id']}", headers=AUTH).json()
    trace = detail["trace"]
    assert detail["reply"] == "Shere Khan is lame."
    assert [s["name"] for s in trace["steps"]] == ["router", "generate"]
    assert {"guard", "router", "retrieval", "generate", "output_check"} <= set(trace["timings"])
    assert trace["passages"] and trace["started_at"] > 0
    assert detail["notes"]["pipeline"]


def test_summary_keeps_no_prompts_or_passage_text_but_full_does(
    tmp_path: Path,
    seeded: Settings,
) -> None:
    client, _ = make_client(tmp_path, seeded)
    ask(client, start(client)["id"])
    summary = client.get("/api/admin/traces/1", headers=AUTH).json()["trace"]
    assert "messages" not in summary["steps"][0] and "text" not in summary["passages"][0]
    assert "Shere" not in json.dumps(summary["steps"])

    full_client, _ = make_client(tmp_path, seeded, TRACE_STORE="full")
    ask(full_client, start(full_client)["id"])
    full = full_client.get("/api/admin/traces/2", headers=AUTH).json()
    assert full["stored"] == "full"
    assert full["trace"]["steps"][0]["messages"] and full["trace"]["passages"][0]["text"]
    assert full["trace"]["steps"][1]["output"] == "Shere Khan is lame."


def test_store_off_saves_nothing(tmp_path: Path, seeded: Settings) -> None:
    client, _ = make_client(tmp_path, seeded, TRACE_STORE="off")
    ask(client, start(client)["id"])
    assert client.get("/api/admin/traces", headers=AUTH).json()["total"] == 0


def test_a_trace_that_cannot_be_saved_never_breaks_the_reply(
    tmp_path: Path,
    seeded: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = make_client(tmp_path, seeded)

    def boom(*_: object) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(play, "save_trace", boom)
    ask(client, start(client)["id"])


def test_turns_that_end_early_are_traced_too(tmp_path: Path, seeded: Settings) -> None:
    client, _ = make_client(tmp_path, seeded, label="off_topic")
    ask(client, start(client)["id"], "What is for dinner?")
    row = client.get("/api/admin/traces", headers=AUTH).json()["items"][0]
    assert row["route"] == "off_topic"
    detail = client.get(f"/api/admin/traces/{row['id']}", headers=AUTH).json()
    assert [s["name"] for s in detail["trace"]["steps"]] == ["router"]


def test_filters_and_stats(tmp_path: Path, seeded: Settings) -> None:
    client, settings = make_client(tmp_path, seeded)
    sid = start(client)["id"]
    ask(client, sid, "Why does Shere Khan limp?")
    ask(client, sid, "Xyzzy plugh?")
    conn = connect(settings.data_dir / "app.db")
    conn.execute("UPDATE turn_traces SET route = 'feelings' WHERE id = 1")
    conn.execute(
        "UPDATE turn_traces SET total_latency_s = 9.0, flags = '[\"ungrounded:no_evidence\"]'"
        " WHERE id = 2"
    )
    conn.close()

    def total(**params: object) -> int:
        r = client.get("/api/admin/traces", headers=AUTH, params=params)  # type: ignore[arg-type]
        assert r.status_code == 200, r.text
        return r.json()["total"]  # type: ignore[no-any-return]

    assert total() == 2
    assert total(route="feelings") == 1
    assert total(min_latency=5) == 1
    assert total(mode="M1") == 2 and total(mode="M2") == 0
    assert total(cached=True) == 0
    assert total(since=time.time() + 60) == 0
    assert total(until=time.time() + 60) == 2
    assert total(flag="ungrounded") == 1 and total(flag="ungrounded:no_evidence") == 1
    assert total(flag="no_hits") == 0 and total(flag="ungrounded%") == 0

    stats = client.get("/api/admin/traces/stats", headers=AUTH).json()
    assert stats["total"] == 2 and stats["by_route"]["feelings"] == 1
    assert stats["latency_p95_s"] >= 9.0 and stats["tokens_per_turn"] >= 0

    page = client.get("/api/admin/traces", headers=AUTH, params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 2 and len(page["items"]) == 1


def test_a_missing_trace_is_a_404(tmp_path: Path, seeded: Settings) -> None:
    client, _ = make_client(tmp_path, seeded)
    r = client.get("/api/admin/traces/99", headers=AUTH)
    assert r.status_code == 404 and r.json()["error"]["code"] == "no_such_trace"


def test_purging_sessions_removes_their_traces_and_old_traces_are_pruned(
    tmp_path: Path,
    seeded: Settings,
) -> None:
    client, settings = make_client(tmp_path, seeded)
    old, keep = start(client)["id"], start(client)["id"]
    ask(client, old)
    ask(client, keep)
    conn = connect(settings.data_dir / "app.db")
    conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (time.time() - 40 * 86400, old))
    assert purge_sessions(conn, 30) == 1
    assert conn.execute("SELECT COUNT(*) FROM turn_traces").fetchone()[0] == 1
    conn.execute("UPDATE turn_traces SET created_at = ?", (time.time() - 40 * 86400,))
    assert prune_traces(conn, 30) == 1
    assert conn.execute("SELECT COUNT(*) FROM session_events WHERE kind = 'ask'").fetchone()[0] == 1
    conn.close()


def test_a_trace_links_to_its_opentelemetry_trace(
    tmp_path: Path, seeded: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from storyquest import telemetry

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "_tracer", provider.get_tracer("test"))
    monkeypatch.setattr(telemetry, "_ready", True)

    client, _ = make_client(tmp_path, seeded, OTEL_VIEWER_URL="http://localhost:16686/")
    ask(client, start(client)["id"])
    (root,) = [s for s in exporter.get_finished_spans() if s.name == "turn"]
    otel_id = f"{root.context.trace_id:032x}"

    found = client.get(f"/api/admin/traces?otel_trace={otel_id[:7]}", headers=AUTH).json()
    assert found["total"] == 1
    assert client.get("/api/admin/traces?otel_trace=ffffff0", headers=AUTH).json()["total"] == 0
    assert client.get("/api/admin/traces?otel_trace=x%27--", headers=AUTH).json()["total"] == 0
    detail = client.get(f"/api/admin/traces/{found['items'][0]['id']}", headers=AUTH).json()
    assert detail["trace"]["otel_trace_id"] == otel_id
    assert detail["otel_url"] == f"http://localhost:16686/trace/{otel_id}"


def test_without_opentelemetry_there_is_no_link(tmp_path: Path, seeded: Settings) -> None:
    client, _ = make_client(tmp_path, seeded)
    ask(client, start(client)["id"])
    row = client.get("/api/admin/traces", headers=AUTH).json()["items"][0]
    detail = client.get(f"/api/admin/traces/{row['id']}", headers=AUTH).json()
    assert detail["trace"]["otel_trace_id"] == "" and detail["otel_url"] == ""
