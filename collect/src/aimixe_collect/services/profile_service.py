"""Profile status, progressive questioning support and value recording (specification §2)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..profile import schema
from ..profile.model import FieldValue, Profile

if TYPE_CHECKING:
    from .app import App


@dataclass
class ProfileStatus:
    known: list[tuple[str, str]] = field(default_factory=list)
    missing: list[tuple[str, str]] = field(default_factory=list)
    uncertain: list[tuple[str, str]] = field(default_factory=list)
    contradictory: list[tuple[str, str]] = field(default_factory=list)

    @property
    def to_ask(self) -> list[tuple[str, str]]:
        """Fields progressive questioning should ask: missing, uncertain or contradictory."""
        seen: set[tuple[str, str]] = set()
        out: list[tuple[str, str]] = []
        for g, f in schema.all_fields():
            key = (g.name, f.name)
            if key in seen:
                continue
            if key in self.missing or key in self.uncertain or key in self.contradictory:
                seen.add(key)
                out.append(key)
        return out

    def group_state(self, group: str) -> str:
        """done | partial | empty for the progress display."""
        fields = [f.name for f in schema.GROUP_BY_NAME[group].fields]
        ask = {f for g, f in self.to_ask if g == group}
        if not ask:
            return "done"
        if len(ask) == len(fields):
            return "empty"
        return "partial"


class ProfileService:
    def __init__(self, app: "App"):
        self.app = app

    def status(self, profile: Profile) -> ProfileStatus:
        thr = self.app.config.uncertain_below
        st = ProfileStatus(known=profile.known_fields(), missing=profile.missing_fields())
        for g, f in profile.known_fields():
            if profile.is_contradictory(g, f):
                st.contradictory.append((g, f))
            elif profile.confidence(g, f) < thr:
                st.uncertain.append((g, f))
        return st

    def set_value(self, profile: Profile, group: str, name: str, value: Any,
                  session_id: str | None = None, note: str | None = None) -> FieldValue:
        fv = profile.set_user_value(group, name, value, session_id=session_id, note=note)
        self.save(profile)
        return fv

    def propose(self, profile: Profile, group: str, name: str, value: Any, source_type: str,
                source: str | None, confidence: float, session_id: str | None = None,
                note: str | None = None) -> FieldValue:
        """A discovered value: recorded as *proposed*; it reaches the canonical profile via review."""
        fv = FieldValue(value=value, source_type=source_type, source=source, confidence=confidence,
                        session_id=session_id, note=note, status="proposed")
        profile.add(group, name, fv)
        self.save(profile)
        return fv

    def prefer(self, profile: Profile, group: str, name: str, value_id: int) -> None:
        for v in profile.field_values(group, name, include_proposed=True):
            v.preferred = v.id == value_id
        self.save(profile)

    def save(self, profile: Profile) -> None:
        self.app.languages.upsert(profile)
        self.app.profiles.save(profile)
        self.write_language_json(profile)

    def write_language_json(self, profile: Profile) -> None:
        path = self.app.paths.language_json(profile.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(profile.to_json(), indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def label(group: str, name: str) -> str:
        return schema.field_spec(group, name).label
