CREATE TABLE books (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en',
    age_band TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    content_notes TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'listed' CHECK (visibility IN ('listed', 'hidden')),
    status TEXT NOT NULL DEFAULT 'allowlisted'
        CHECK (status IN ('allowlisted', 'ingesting', 'ready', 'failed')),
    raw_path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE chapters (
    book_id INTEGER NOT NULL REFERENCES books (id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('story', 'poem', 'front', 'back')),
    included INTEGER NOT NULL DEFAULT 1,
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    PRIMARY KEY (book_id, idx)
);

CREATE TABLE beats (
    book_id INTEGER NOT NULL,
    chapter_idx INTEGER NOT NULL,
    idx INTEGER NOT NULL,
    title TEXT NOT NULL,
    narration TEXT NOT NULL,
    clues TEXT NOT NULL DEFAULT '[]',
    vocabulary TEXT NOT NULL DEFAULT '[]',
    choice TEXT NOT NULL DEFAULT '{}',
    spoiler_reveals TEXT NOT NULL DEFAULT '[]',
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'draft' CHECK (review_status IN ('draft', 'approved')),
    PRIMARY KEY (book_id, chapter_idx, idx),
    FOREIGN KEY (book_id, chapter_idx) REFERENCES chapters (book_id, idx) ON DELETE CASCADE
);

CREATE TABLE chunks (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL,
    chapter_idx INTEGER NOT NULL,
    beat_idx INTEGER NOT NULL,
    idx INTEGER NOT NULL,
    text TEXT NOT NULL,
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    FOREIGN KEY (book_id, chapter_idx) REFERENCES chapters (book_id, idx) ON DELETE CASCADE
);

CREATE INDEX chunks_position ON chunks (book_id, chapter_idx, beat_idx);

CREATE VIRTUAL TABLE chunks_fts USING fts5 (
    text, content = 'chunks', content_rowid = 'id', tokenize = 'porter unicode61'
);

CREATE TRIGGER chunks_after_insert AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts (rowid, text) VALUES (new.id, new.text);
END;

CREATE TRIGGER chunks_after_delete AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts (chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;

CREATE TRIGGER chunks_after_update AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts (chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO chunks_fts (rowid, text) VALUES (new.id, new.text);
END;
