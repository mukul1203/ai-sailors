-- Beats made by the LLM stages carry where they came from, the source words behind each clue
-- and validation flags; entity cards; and the bookkeeping that makes ingestion resumable.

ALTER TABLE beats ADD COLUMN source TEXT NOT NULL DEFAULT 'spine';
ALTER TABLE beats ADD COLUMN clue_quotes TEXT NOT NULL DEFAULT '[]';
ALTER TABLE beats ADD COLUMN flags TEXT NOT NULL DEFAULT '[]';
ALTER TABLE beats ADD COLUMN pipeline_version TEXT NOT NULL DEFAULT '';

CREATE TABLE entities (
    book_id INTEGER NOT NULL REFERENCES books (id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('character', 'place', 'term')),
    aliases TEXT NOT NULL DEFAULT '[]',
    card TEXT NOT NULL,
    first_char INTEGER NOT NULL,
    card_chapter INTEGER NOT NULL DEFAULT 0,
    card_beat INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (book_id, key)
);

-- One row per book, chapter and step (chapter -1 for steps about the whole book). A step is
-- skipped when its stored input_hash matches, so a rerun resumes where a failure stopped.
CREATE TABLE ingestion_steps (
    book_id INTEGER NOT NULL REFERENCES books (id) ON DELETE CASCADE,
    chapter_idx INTEGER NOT NULL,
    step TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('done', 'failed')),
    detail TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (book_id, chapter_idx, step)
);

CREATE TABLE ingestion_jobs (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES books (id) ON DELETE CASCADE,
    options TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    finished_at TEXT
);
