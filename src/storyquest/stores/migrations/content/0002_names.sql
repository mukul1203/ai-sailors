CREATE TABLE names (
    book_id INTEGER NOT NULL REFERENCES books (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    first_char INTEGER NOT NULL,
    PRIMARY KEY (book_id, name)
);
