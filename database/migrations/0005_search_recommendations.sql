PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recommendation_type TEXT NOT NULL,
    priority TEXT NOT NULL,
    reason TEXT NOT NULL,
    affected_items TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS duplicate_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_a_path TEXT NOT NULL,
    file_b_path TEXT NOT NULL,
    similarity REAL NOT NULL,
    duplicate_type TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_recommendations_type ON recommendations(recommendation_type);
CREATE INDEX IF NOT EXISTS idx_recommendations_status ON recommendations(status);
CREATE INDEX IF NOT EXISTS idx_duplicate_reports_paths ON duplicate_reports(file_a_path, file_b_path);
