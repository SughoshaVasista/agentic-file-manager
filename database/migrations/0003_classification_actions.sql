PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agent_action_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    source_path TEXT,
    destination_path TEXT,
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS folder_statistics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    root_path TEXT NOT NULL,
    total_folders INTEGER NOT NULL,
    total_files INTEGER NOT NULL,
    max_depth INTEGER NOT NULL,
    categories_json TEXT NOT NULL,
    subcategories_json TEXT NOT NULL,
    analyzed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS classification_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    category TEXT NOT NULL,
    confidence REAL NOT NULL,
    destination_path TEXT NOT NULL,
    decision_score REAL NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_action_logs_timestamp ON agent_action_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_agent_action_logs_status ON agent_action_logs(status);
CREATE INDEX IF NOT EXISTS idx_folder_statistics_root_path ON folder_statistics(root_path);
CREATE INDEX IF NOT EXISTS idx_classification_history_file_path ON classification_history(file_path);
CREATE INDEX IF NOT EXISTS idx_classification_history_category ON classification_history(category);
