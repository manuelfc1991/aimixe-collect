"""SQLite connection and schema management."""
from __future__ import annotations

import sqlite3
from importlib import resources as ilr
from pathlib import Path

SCHEMA_VERSION = 2


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    # autocommit + WAL: several runs (a scan in the terminal, a download in the browser) can write at
    # the same time; no statement ever holds the write lock while a download or extraction runs.
    conn = sqlite3.connect(str(path), timeout=60, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    _apply_schema(conn)
    return conn


def _apply_schema(conn: sqlite3.Connection) -> None:
    sql = ilr.files("aimixe_collect.db").joinpath("schema.sql").read_text(encoding="utf-8")
    conn.executescript(sql)
    row = conn.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_meta(key, value) VALUES ('version', ?)", (str(SCHEMA_VERSION),))
    else:
        _migrate(conn, int(row["value"]))
    conn.commit()


def _migrate(conn: sqlite3.Connection, from_version: int) -> None:
    """Additive migrations live here. v2 added resource_signature and resource_near_duplicate
    (created by the CREATE IF NOT EXISTS statements above)."""
    if from_version < SCHEMA_VERSION:
        conn.execute("UPDATE schema_meta SET value=? WHERE key='version'", (str(SCHEMA_VERSION),))
