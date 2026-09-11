-- AImixE Data Collection Module — authoritative metadata index (specification §11).
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS language (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    iso639_3        TEXT,
    identifier_type TEXT NOT NULL CHECK (identifier_type IN ('iso', 'local')),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- Profile fields are rows, not columns: a new field needs no migration (§2.8).
CREATE TABLE IF NOT EXISTS profile_value (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    language_id  TEXT NOT NULL REFERENCES language(id),
    grp          TEXT NOT NULL,
    field        TEXT NOT NULL,
    value_json   TEXT NOT NULL,
    source_type  TEXT NOT NULL,
    source       TEXT,
    year         INTEGER,
    confidence   REAL NOT NULL DEFAULT 1.0,
    preferred    INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'accepted' CHECK (status IN ('accepted', 'proposed', 'rejected')),
    note         TEXT,
    session_id   TEXT,
    recorded_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_profile_value_lang ON profile_value(language_id, grp, field);

CREATE TABLE IF NOT EXISTS resource (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256        TEXT NOT NULL UNIQUE,
    size          INTEGER NOT NULL,
    original_name TEXT NOT NULL,
    format        TEXT NOT NULL,
    mime          TEXT,
    category      TEXT NOT NULL,
    stored_path   TEXT NOT NULL,
    storage_mode  TEXT NOT NULL CHECK (storage_mode IN ('copy', 'move', 'reference')),
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resource_language (
    resource_id     INTEGER NOT NULL REFERENCES resource(id),
    language_id     TEXT NOT NULL REFERENCES language(id),
    relevance_score INTEGER NOT NULL,
    band            TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('confirmed', 'uncertain', 'rejected')),
    reasons_json    TEXT NOT NULL DEFAULT '[]',
    recorded_at     TEXT NOT NULL,
    PRIMARY KEY (resource_id, language_id)
);

CREATE TABLE IF NOT EXISTS resource_type (
    resource_id INTEGER NOT NULL REFERENCES resource(id),
    type        TEXT NOT NULL,
    confidence  REAL NOT NULL DEFAULT 1.0,
    source      TEXT NOT NULL DEFAULT 'rule',
    PRIMARY KEY (resource_id, type, source)
);

-- One row per discovery of a resource. A duplicate adds a row here, never a second file (§13).
CREATE TABLE IF NOT EXISTS resource_source (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_id      INTEGER NOT NULL REFERENCES resource(id),
    language_id      TEXT NOT NULL REFERENCES language(id),
    session_id       TEXT,
    method           TEXT NOT NULL CHECK (method IN ('catalogue', 'agent', 'offline', 'import')),
    source_url       TEXT,
    catalogue        TEXT,
    resource_url     TEXT,
    query            TEXT,
    discovery_date   TEXT,
    download_date    TEXT,
    licence          TEXT,
    original_path    TEXT,
    detection_method TEXT,
    confidence       REAL,
    import_method    TEXT,
    recorded_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_resource_source_res ON resource_source(resource_id);

CREATE TABLE IF NOT EXISTS resource_metadata (
    resource_id  INTEGER NOT NULL REFERENCES resource(id),
    key          TEXT NOT NULL,
    value        TEXT,
    extracted_by TEXT NOT NULL DEFAULT 'basic',
    PRIMARY KEY (resource_id, key, extracted_by)
);

CREATE TABLE IF NOT EXISTS extraction (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_id INTEGER NOT NULL REFERENCES resource(id),
    kind        TEXT NOT NULL,
    path        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session (
    id             TEXT PRIMARY KEY,
    language_id    TEXT NOT NULL REFERENCES language(id),
    mode           TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('running', 'finished', 'interrupted', 'failed')),
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    discovered     INTEGER NOT NULL DEFAULT 0,
    relevant       INTEGER NOT NULL DEFAULT 0,
    downloaded     INTEGER NOT NULL DEFAULT 0,
    duplicates     INTEGER NOT NULL DEFAULT 0,
    failed         INTEGER NOT NULL DEFAULT 0,
    pending_review INTEGER NOT NULL DEFAULT 0,
    params_json    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS session_event (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES session(id),
    ts         TEXT NOT NULL,
    level      TEXT NOT NULL,
    message    TEXT NOT NULL,
    data_json  TEXT
);
CREATE INDEX IF NOT EXISTS ix_session_event ON session_event(session_id);

CREATE TABLE IF NOT EXISTS review_item (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    language_id  TEXT NOT NULL REFERENCES language(id),
    session_id   TEXT,
    kind         TEXT NOT NULL CHECK (kind IN ('resource', 'profile_field')),
    payload_json TEXT NOT NULL,
    confidence   REAL,
    source_ref   TEXT,
    status       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected', 'skipped')),
    created_at   TEXT NOT NULL,
    decided_at   TEXT,
    decided_by   TEXT
);

CREATE TABLE IF NOT EXISTS resource_signature (
    resource_id INTEGER PRIMARY KEY REFERENCES resource(id),
    kind        TEXT NOT NULL,
    values_json TEXT NOT NULL,
    tokens      INTEGER NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resource_near_duplicate (
    resource_id INTEGER NOT NULL REFERENCES resource(id),
    other_id    INTEGER NOT NULL REFERENCES resource(id),
    similarity  REAL NOT NULL,
    method      TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (resource_id, other_id)
);

CREATE TABLE IF NOT EXISTS catalogue_provider (
    name     TEXT PRIMARY KEY,
    path     TEXT NOT NULL,
    enabled  INTEGER NOT NULL DEFAULT 1,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS id_counter (
    prefix TEXT PRIMARY KEY,
    value  INTEGER NOT NULL
);
