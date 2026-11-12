-- One vector per chunk and embedding model. Rebuilt by `make embed`; deleted with the chunk.
CREATE TABLE chunk_embeddings (
    chunk_id INTEGER NOT NULL REFERENCES chunks (id) ON DELETE CASCADE,
    model_id TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY (chunk_id, model_id)
);
