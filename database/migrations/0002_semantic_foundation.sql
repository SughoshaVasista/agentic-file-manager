PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS vector_metadata (
    vector_id INTEGER PRIMARY KEY,
    file_id INTEGER,
    file_name TEXT NOT NULL,
    file_type TEXT NOT NULL,
    chunk_index INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS file_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    vector_id INTEGER NOT NULL UNIQUE,
    model_name TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    FOREIGN KEY (vector_id) REFERENCES vector_metadata(vector_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_vector_metadata_file_id ON vector_metadata(file_id);
CREATE INDEX IF NOT EXISTS idx_vector_metadata_file_type ON vector_metadata(file_type);
CREATE INDEX IF NOT EXISTS idx_file_embeddings_file_id ON file_embeddings(file_id);
