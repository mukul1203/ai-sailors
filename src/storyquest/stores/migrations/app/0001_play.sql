-- A play session: where a child is in one chapter, and what they did. The server owns all of it;
-- the client only sends a choice id or a question. No account and no personal data: a session
-- is an anonymous id, and `purge-sessions` deletes old ones.

CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    book_id INTEGER NOT NULL,
    chapter_idx INTEGER NOT NULL,
    beat_idx INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed')),
    mode TEXT NOT NULL,
    questions INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE session_events (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('choice', 'ask')),
    beat_idx INTEGER NOT NULL,
    text TEXT NOT NULL,  -- the card id, or the child's question
    reply TEXT NOT NULL DEFAULT '',
    route TEXT NOT NULL DEFAULT '',
    flags TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL
);

CREATE INDEX session_events_session ON session_events (session_id, id);
