-- One row per question a child asked: how the agent handled it. Written by `play.ask`, read by
-- the admin trace dashboard. The `trace` JSON holds the per-step detail (prompts and passage
-- text only when TRACE_STORE=full). Rows go with their session (cascade), so `purge-sessions`
-- removes them, and old rows are pruned by TRACE_RETENTION_DAYS.

CREATE TABLE turn_traces (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    event_id INTEGER REFERENCES session_events (id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    mode TEXT NOT NULL,
    route TEXT NOT NULL,
    stored TEXT NOT NULL CHECK (stored IN ('summary', 'full')),
    total_latency_s REAL NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    any_cached INTEGER NOT NULL DEFAULT 0,
    flags TEXT NOT NULL DEFAULT '[]',
    trace TEXT NOT NULL
);

CREATE INDEX turn_traces_created ON turn_traces (created_at);
CREATE INDEX turn_traces_session ON turn_traces (session_id);
