PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS learned_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,
    preferred_destination TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    usage_count INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (pattern, preferred_destination)
);

CREATE TABLE IF NOT EXISTS planning_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL UNIQUE,
    root_path TEXT NOT NULL,
    environment_json TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    risk_level TEXT NOT NULL,
    estimated_actions INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS plan_execution_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    status TEXT NOT NULL,
    source_path TEXT,
    destination_path TEXT,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (plan_id) REFERENCES planning_sessions(plan_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_learned_preferences_pattern ON learned_preferences(pattern);
CREATE INDEX IF NOT EXISTS idx_learned_preferences_destination ON learned_preferences(preferred_destination);
CREATE INDEX IF NOT EXISTS idx_planning_sessions_plan_id ON planning_sessions(plan_id);
CREATE INDEX IF NOT EXISTS idx_planning_sessions_status ON planning_sessions(status);
CREATE INDEX IF NOT EXISTS idx_plan_execution_logs_plan_id ON plan_execution_logs(plan_id);
CREATE INDEX IF NOT EXISTS idx_plan_execution_logs_status ON plan_execution_logs(status);
