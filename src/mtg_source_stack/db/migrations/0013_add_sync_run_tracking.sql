CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    trigger_kind TEXT NOT NULL DEFAULT 'cli',
    source_name TEXT,
    limit_value INTEGER,
    snapshot_path TEXT,
    summary_json TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_sync_runs_started_at
    ON sync_runs (started_at DESC);

CREATE INDEX IF NOT EXISTS idx_sync_runs_kind_started_at
    ON sync_runs (run_kind, started_at DESC);

CREATE TABLE IF NOT EXISTS sync_run_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_run_id INTEGER NOT NULL,
    step_name TEXT NOT NULL,
    status TEXT NOT NULL,
    rows_seen INTEGER,
    rows_written INTEGER,
    rows_skipped INTEGER,
    details_json TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    FOREIGN KEY (sync_run_id) REFERENCES sync_runs (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sync_run_steps_run_step
    ON sync_run_steps (sync_run_id, step_name);

CREATE TABLE IF NOT EXISTS sync_run_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_run_id INTEGER NOT NULL,
    artifact_role TEXT NOT NULL,
    source_url TEXT,
    local_path TEXT,
    bytes_written INTEGER,
    sha256 TEXT,
    etag TEXT,
    last_modified TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sync_run_id) REFERENCES sync_runs (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sync_run_artifacts_run_role
    ON sync_run_artifacts (sync_run_id, artifact_role);

CREATE TABLE IF NOT EXISTS sync_run_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_run_id INTEGER NOT NULL,
    step_name TEXT,
    level TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sync_run_id) REFERENCES sync_runs (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sync_run_issues_run_created_at
    ON sync_run_issues (sync_run_id, created_at);
