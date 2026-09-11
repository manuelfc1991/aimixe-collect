"""Review queue (specification §18): uncertain resources and proposed profile facts."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..profile.model import Profile

if TYPE_CHECKING:
    from .app import App


@dataclass
class ReviewItem:
    id: int
    language_id: str
    session_id: str | None
    kind: str                 # resource | profile_field
    payload: dict[str, Any]
    confidence: float | None
    source_ref: str | None
    status: str
    created_at: str


class ReviewService:
    def __init__(self, app: "App"):
        self.app = app

    def _item(self, r) -> ReviewItem:
        return ReviewItem(id=r["id"], language_id=r["language_id"], session_id=r["session_id"], kind=r["kind"],
                          payload=json.loads(r["payload_json"]), confidence=r["confidence"],
                          source_ref=r["source_ref"], status=r["status"], created_at=r["created_at"])

    def pending(self, language_id: str | None = None) -> list[ReviewItem]:
        return [self._item(r) for r in self.app.reviews.pending(language_id)]

    def summary(self) -> list[dict]:
        """Per language: how many items wait, split into resources and language facts."""
        rows = self.app.conn.execute(
            "SELECT ri.language_id, l.name, l.iso639_3, ri.kind, count(*) AS n FROM review_item ri "
            "JOIN language l ON l.id = ri.language_id WHERE ri.status='pending' "
            "GROUP BY ri.language_id, ri.kind ORDER BY l.name").fetchall()
        out: dict[str, dict] = {}
        for r in rows:
            d = out.setdefault(r["language_id"], {"language_id": r["language_id"], "name": r["name"],
                                                    "iso639_3": r["iso639_3"], "resources": 0, "facts": 0, "total": 0})
            d["resources" if r["kind"] == "resource" else "facts"] += r["n"]
            d["total"] += r["n"]
        return list(out.values())

    def propose_profile_field(self, profile: Profile, group: str, field: str, value: Any,
                              confidence: float, source_ref: str, source_type: str = "agent",
                              session_id: str | None = None, quote: str | None = None) -> int:
        fv = self.app.profile_service.propose(profile, group, field, value, source_type, source_ref,
                                              confidence, session_id=session_id, note=quote)
        return self.app.reviews.add(profile.id, session_id, "profile_field",
                                    {"group": group, "field": field, "value": value, "value_id": fv.id,
                                     "source_type": source_type, "quote": quote}, confidence, source_ref)

    def accept(self, item: ReviewItem) -> None:
        if item.kind == "profile_field":
            profile = self.app.language_service.load(item.language_id)
            if profile is not None:
                for v in profile.field_values(item.payload["group"], item.payload["field"], include_proposed=True):
                    if v.id == item.payload.get("value_id"):
                        v.status = "accepted"
                self.app.profile_service.save(profile)
        elif item.kind == "resource":
            rid = item.payload.get("resource_id")
            if rid:
                self.app.conn.execute(
                    "UPDATE resource_language SET status='confirmed' WHERE resource_id=? AND language_id=?",
                    (rid, item.language_id))
        self.app.reviews.decide(item.id, "accepted")

    def reject(self, item: ReviewItem) -> None:
        if item.kind == "profile_field":
            profile = self.app.language_service.load(item.language_id)
            if profile is not None:
                for v in profile.field_values(item.payload["group"], item.payload["field"], include_proposed=True):
                    if v.id == item.payload.get("value_id"):
                        v.status = "rejected"
                self.app.profile_service.save(profile)
        elif item.kind == "resource":
            rid = item.payload.get("resource_id")
            if rid:
                self.app.conn.execute(
                    "UPDATE resource_language SET status='rejected' WHERE resource_id=? AND language_id=?",
                    (rid, item.language_id))
        self.app.reviews.decide(item.id, "rejected")

    def skip(self, item: ReviewItem) -> None:
        self.app.reviews.decide(item.id, "skipped")

    def source_text(self, item: ReviewItem, limit: int = 4000) -> str:
        """Best-effort view of the item's source for the [V] option."""
        ref = item.source_ref or item.payload.get("path")
        if not ref:
            return "(no source reference)"
        from pathlib import Path
        p = Path(str(ref))
        if p.is_file():
            try:
                raw = p.read_bytes()[:limit]
                if b"\x00" in raw:
                    return f"{p}\n(binary file, {p.stat().st_size} bytes)"
                return f"{p}\n\n" + raw.decode("utf-8", "replace")
            except OSError as exc:
                return f"{p}\n(unreadable: {exc})"
        return str(ref)
