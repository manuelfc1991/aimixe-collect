"""Repositories: the only place SQL is written."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..logging_setup import now_iso
from ..profile.model import FieldValue, Profile


class LanguageRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert(self, profile: Profile) -> None:
        ts = now_iso()
        self.conn.execute(
            "INSERT INTO language(id, name, iso639_3, identifier_type, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, "
            "iso639_3=excluded.iso639_3, identifier_type=excluded.identifier_type, updated_at=excluded.updated_at",
            (profile.id, profile.name, profile.iso639_3, profile.identifier_type, ts, ts))
        self.conn.commit()

    def get(self, language_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM language WHERE id=?", (language_id,)).fetchone()

    def list(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM language ORDER BY name").fetchall()


class ProfileRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def load(self, profile: Profile) -> Profile:
        rows = self.conn.execute(
            "SELECT * FROM profile_value WHERE language_id=? ORDER BY id", (profile.id,)).fetchall()
        profile.values = {}
        for r in rows:
            fv = FieldValue(value=json.loads(r["value_json"]), source_type=r["source_type"],
                            source=r["source"], year=r["year"], confidence=r["confidence"],
                            recorded_at=r["recorded_at"], session_id=r["session_id"],
                            preferred=bool(r["preferred"]), note=r["note"], status=r["status"], id=r["id"])
            profile.values.setdefault(r["grp"], {}).setdefault(r["field"], []).append(fv)
        return profile

    def save(self, profile: Profile) -> None:
        """Persist every in-memory envelope; existing rows are updated, new ones inserted."""
        for grp, fields in profile.values.items():
            for name, vals in fields.items():
                for fv in vals:
                    if fv.id is None:
                        cur = self.conn.execute(
                            "INSERT INTO profile_value(language_id, grp, field, value_json, source_type, source, "
                            "year, confidence, preferred, status, note, session_id, recorded_at) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (profile.id, grp, name, json.dumps(fv.value, ensure_ascii=False), fv.source_type,
                             fv.source, fv.year, fv.confidence, int(fv.preferred), fv.status, fv.note,
                             fv.session_id, fv.recorded_at))
                        fv.id = cur.lastrowid
                    else:
                        self.conn.execute(
                            "UPDATE profile_value SET value_json=?, confidence=?, preferred=?, status=?, note=? "
                            "WHERE id=?",
                            (json.dumps(fv.value, ensure_ascii=False), fv.confidence, int(fv.preferred),
                             fv.status, fv.note, fv.id))
        self.conn.commit()


@dataclass
class ResourceRow:
    id: int
    sha256: str
    size: int
    original_name: str
    format: str
    mime: str | None
    category: str
    stored_path: str
    storage_mode: str
    created_at: str


class ResourceRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def by_hash(self, sha256: str) -> ResourceRow | None:
        r = self.conn.execute("SELECT * FROM resource WHERE sha256=?", (sha256,)).fetchone()
        return ResourceRow(**dict(r)) if r else None

    def insert(self, sha256: str, size: int, original_name: str, fmt: str, mime: str | None,
               category: str, stored_path: str, storage_mode: str) -> ResourceRow:
        ts = now_iso()
        cur = self.conn.execute(
            "INSERT INTO resource(sha256, size, original_name, format, mime, category, stored_path, storage_mode, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (sha256, size, original_name, fmt, mime, category, stored_path, storage_mode, ts))
        return ResourceRow(cur.lastrowid, sha256, size, original_name, fmt, mime, category, stored_path, storage_mode, ts)

    def set_language(self, resource_id: int, language_id: str, score: int, band: str, status: str,
                     reasons: list[str]) -> None:
        self.conn.execute(
            "INSERT INTO resource_language(resource_id, language_id, relevance_score, band, status, reasons_json, recorded_at) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(resource_id, language_id) DO UPDATE SET "
            "relevance_score=MAX(relevance_score, excluded.relevance_score), "
            "band=CASE WHEN excluded.relevance_score > relevance_score THEN excluded.band ELSE band END, "
            "status=CASE WHEN excluded.relevance_score > relevance_score THEN excluded.status ELSE status END, "
            "reasons_json=excluded.reasons_json",
            (resource_id, language_id, score, band, status, json.dumps(reasons, ensure_ascii=False), now_iso()))

    def language_status(self, resource_id: int, language_id: str) -> str | None:
        r = self.conn.execute("SELECT status FROM resource_language WHERE resource_id=? AND language_id=?",
                              (resource_id, language_id)).fetchone()
        return r["status"] if r else None

    def add_types(self, resource_id: int, types: list[tuple[str, float, str]]) -> None:
        for t, conf, src in types:
            self.conn.execute(
                "INSERT INTO resource_type(resource_id, type, confidence, source) VALUES (?,?,?,?) "
                "ON CONFLICT(resource_id, type, source) DO UPDATE SET confidence=MAX(confidence, excluded.confidence)",
                (resource_id, t, conf, src))

    def add_source(self, resource_id: int, language_id: str, session_id: str | None, method: str,
                   **prov: Any) -> int:
        cols = ["resource_id", "language_id", "session_id", "method", "recorded_at"]
        vals: list[Any] = [resource_id, language_id, session_id, method, now_iso()]
        for k in ("source_url", "catalogue", "resource_url", "query", "discovery_date", "download_date",
                  "licence", "original_path", "detection_method", "confidence", "import_method"):
            if prov.get(k) is not None:
                cols.append(k)
                vals.append(prov[k])
        cur = self.conn.execute(
            f"INSERT INTO resource_source({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
        return cur.lastrowid

    def add_metadata(self, resource_id: int, meta: dict[str, Any], extracted_by: str = "basic") -> None:
        for k, v in meta.items():
            if v is None:
                continue
            self.conn.execute(
                "INSERT INTO resource_metadata(resource_id, key, value, extracted_by) VALUES (?,?,?,?) "
                "ON CONFLICT(resource_id, key, extracted_by) DO UPDATE SET value=excluded.value",
                (resource_id, k, str(v), extracted_by))

    def add_extraction(self, resource_id: int, kind: str, path: str) -> None:
        self.conn.execute("INSERT INTO extraction(resource_id, kind, path, created_at) VALUES (?,?,?,?)",
                          (resource_id, kind, path, now_iso()))

    def set_signature(self, resource_id: int, kind: str, values: list[int], tokens: int) -> None:
        self.conn.execute(
            "INSERT INTO resource_signature(resource_id, kind, values_json, tokens, created_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(resource_id) DO UPDATE SET kind=excluded.kind, values_json=excluded.values_json, tokens=excluded.tokens",
            (resource_id, kind, json.dumps(values), tokens, now_iso()))

    def signatures_for_language(self, language_id: str, kind: str, exclude: int | None = None) -> list[tuple[int, list[int], int]]:
        rows = self.conn.execute(
            "SELECT s.resource_id, s.values_json, s.tokens FROM resource_signature s "
            "JOIN resource_language rl ON rl.resource_id = s.resource_id WHERE rl.language_id=? AND s.kind=?",
            (language_id, kind)).fetchall()
        return [(r["resource_id"], json.loads(r["values_json"]), r["tokens"]) for r in rows if r["resource_id"] != exclude]

    def add_near_duplicate(self, resource_id: int, other_id: int, similarity: float, method: str) -> None:
        for a, b in ((resource_id, other_id), (other_id, resource_id)):
            self.conn.execute(
                "INSERT INTO resource_near_duplicate(resource_id, other_id, similarity, method, recorded_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(resource_id, other_id) DO UPDATE SET similarity=excluded.similarity",
                (a, b, similarity, method, now_iso()))

    def near_duplicates(self, resource_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT nd.other_id, nd.similarity, nd.method, r.original_name FROM resource_near_duplicate nd "
            "JOIN resource r ON r.id = nd.other_id WHERE nd.resource_id=? ORDER BY nd.similarity DESC", (resource_id,)).fetchall()

    def extractions(self, resource_id: int) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM extraction WHERE resource_id=? ORDER BY id", (resource_id,)).fetchall()

    def session_bytes(self, session_id: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(r.size), 0) FROM resource r WHERE r.id IN "
            "(SELECT DISTINCT resource_id FROM resource_source WHERE session_id=?)", (session_id,)).fetchone()
        return int(row[0] or 0)

    def for_language(self, language_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT r.*, rl.relevance_score, rl.band, rl.status, "
            "(SELECT group_concat(type, ', ') FROM resource_type t WHERE t.resource_id=r.id) AS types, "
            "(SELECT count(*) FROM resource_source s WHERE s.resource_id=r.id) AS source_count "
            "FROM resource r JOIN resource_language rl ON rl.resource_id=r.id "
            "WHERE rl.language_id=? ORDER BY r.created_at DESC", (language_id,)).fetchall()

    def sources(self, resource_id: int) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM resource_source WHERE resource_id=? ORDER BY id",
                                 (resource_id,)).fetchall()

    def count_for_language(self, language_id: str) -> int:
        return self.conn.execute("SELECT count(*) FROM resource_language WHERE language_id=?",
                                 (language_id,)).fetchone()[0]

    def commit(self) -> None:
        self.conn.commit()


class SessionRepo:
    COUNTERS = ("discovered", "relevant", "downloaded", "duplicates", "failed", "pending_review")

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def new_id(self, today: datetime | None = None) -> str:
        day = (today or datetime.now()).strftime("%Y%m%d")
        prefix = f"COL-{day}"
        row = self.conn.execute("SELECT value FROM id_counter WHERE prefix=?", (prefix,)).fetchone()
        n = (row["value"] if row else 0) + 1
        self.conn.execute("INSERT INTO id_counter(prefix, value) VALUES (?,?) "
                          "ON CONFLICT(prefix) DO UPDATE SET value=excluded.value", (prefix, n))
        return f"{prefix}-{n:03d}"

    def create(self, language_id: str, mode: str, params: dict[str, Any] | None = None) -> str:
        sid = self.new_id()
        self.conn.execute(
            "INSERT INTO session(id, language_id, mode, status, started_at, params_json) VALUES (?,?,?,?,?,?)",
            (sid, language_id, mode, "running", now_iso(), json.dumps(params or {}, ensure_ascii=False)))
        self.conn.commit()
        return sid

    def bump(self, session_id: str, counter: str, by: int = 1) -> None:
        if counter not in self.COUNTERS:
            raise ValueError(counter)
        self.conn.execute(f"UPDATE session SET {counter} = {counter} + ? WHERE id=?", (by, session_id))

    def event(self, session_id: str, level: str, message: str, data: dict[str, Any] | None = None) -> None:
        self.conn.execute("INSERT INTO session_event(session_id, ts, level, message, data_json) VALUES (?,?,?,?,?)",
                          (session_id, now_iso(), level, message,
                           json.dumps(data, ensure_ascii=False, default=str) if data else None))

    def finish(self, session_id: str, status: str = "finished") -> None:
        self.conn.execute("UPDATE session SET status=?, finished_at=? WHERE id=?", (status, now_iso(), session_id))
        self.conn.commit()

    def get(self, session_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM session WHERE id=?", (session_id,)).fetchone()

    def list(self, language_id: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
        if language_id:
            return self.conn.execute("SELECT * FROM session WHERE language_id=? ORDER BY started_at DESC LIMIT ?",
                                     (language_id, limit)).fetchall()
        return self.conn.execute("SELECT * FROM session ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()

    def events(self, session_id: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM session_event WHERE session_id=? ORDER BY id", (session_id,)).fetchall()

    def commit(self) -> None:
        self.conn.commit()


class ReviewRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, language_id: str, session_id: str | None, kind: str, payload: dict[str, Any],
            confidence: float | None, source_ref: str | None) -> int:
        cur = self.conn.execute(
            "INSERT INTO review_item(language_id, session_id, kind, payload_json, confidence, source_ref, status, created_at) "
            "VALUES (?,?,?,?,?,?,'pending',?)",
            (language_id, session_id, kind, json.dumps(payload, ensure_ascii=False, default=str), confidence,
             source_ref, now_iso()))
        return cur.lastrowid

    def pending(self, language_id: str | None = None) -> list[sqlite3.Row]:
        if language_id:
            return self.conn.execute("SELECT * FROM review_item WHERE status='pending' AND language_id=? ORDER BY id",
                                     (language_id,)).fetchall()
        return self.conn.execute("SELECT * FROM review_item WHERE status='pending' ORDER BY id").fetchall()

    def decide(self, item_id: int, status: str, by: str = "user") -> None:
        self.conn.execute("UPDATE review_item SET status=?, decided_at=?, decided_by=? WHERE id=?",
                          (status, now_iso(), by, item_id))
        self.conn.commit()

    def get(self, item_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM review_item WHERE id=?", (item_id,)).fetchone()
