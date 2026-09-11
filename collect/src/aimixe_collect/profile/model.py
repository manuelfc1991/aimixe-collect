"""Language profile model with per-value provenance (specification §2.8, §2.9).

A field holds a *list* of ``FieldValue`` envelopes. Several may coexist when sources
disagree; one may be marked preferred; none is silently replaced.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..logging_setup import now_iso
from . import schema

SOURCE_TYPES = (
    "user", "local_database", "catalogue", "agent", "academic_source",
    "government_source", "community_source", "inferred", "unknown",
)


@dataclass
class FieldValue:
    value: Any
    source_type: str = "user"
    source: str | None = None
    year: int | None = None
    confidence: float = 1.0
    recorded_at: str = field(default_factory=now_iso)
    session_id: str | None = None
    preferred: bool = False
    note: str | None = None
    status: str = "accepted"         # accepted | proposed | rejected
    id: int | None = None            # database row id when persisted

    def envelope(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("id", None)
        return {k: v for k, v in d.items() if v is not None and v is not False}


@dataclass
class Profile:
    id: str
    name: str
    iso639_3: str | None = None
    identifier_type: str = "iso"        # iso | local
    schema_version: int = 1
    # group -> field -> [FieldValue]
    values: dict[str, dict[str, list[FieldValue]]] = field(default_factory=dict)

    # ---------------------------------------------------------------- access
    def field_values(self, group: str, name: str, include_proposed: bool = False) -> list[FieldValue]:
        vals = self.values.get(group, {}).get(name, [])
        if include_proposed:
            return list(vals)
        return [v for v in vals if v.status == "accepted"]

    def preferred(self, group: str, name: str) -> FieldValue | None:
        vals = self.field_values(group, name)
        if not vals:
            return None
        for v in vals:
            if v.preferred:
                return v
        return max(vals, key=lambda v: (v.confidence, v.recorded_at))

    def is_known(self, group: str, name: str) -> bool:
        return bool(self.field_values(group, name))

    def confidence(self, group: str, name: str) -> float:
        p = self.preferred(group, name)
        return p.confidence if p else 0.0

    def is_contradictory(self, group: str, name: str) -> bool:
        vals = self.field_values(group, name)
        spec = schema.field_spec(group, name)
        if spec.multi or len(vals) < 2:
            return False
        if any(v.preferred for v in vals):
            return False
        return len({_key(v.value) for v in vals}) > 1

    def add(self, group: str, name: str, fv: FieldValue) -> FieldValue:
        bucket = self.values.setdefault(group, {}).setdefault(name, [])
        for existing in bucket:
            if existing.source_type == fv.source_type and _key(existing.value) == _key(fv.value):
                existing.confidence = max(existing.confidence, fv.confidence)
                existing.status = "accepted" if fv.status == "accepted" else existing.status
                return existing
        bucket.append(fv)
        return fv

    def set_user_value(self, group: str, name: str, value: Any, session_id: str | None = None,
                       note: str | None = None) -> FieldValue:
        """Record what the user typed, mark it preferred; keep other sources' values."""
        for v in self.field_values(group, name):
            v.preferred = False
        fv = FieldValue(value=value, source_type="user", source="user", confidence=1.0,
                        session_id=session_id, preferred=True, note=note)
        return self.add(group, name, fv)

    def known_fields(self) -> list[tuple[str, str]]:
        return [(g.name, f.name) for g, f in schema.all_fields() if self.is_known(g.name, f.name)]

    def missing_fields(self) -> list[tuple[str, str]]:
        return [(g.name, f.name) for g, f in schema.all_fields() if not self.is_known(g.name, f.name)]

    def uncertain_fields(self, threshold: float) -> list[tuple[str, str]]:
        out = []
        for g, f in schema.all_fields():
            if self.is_known(g.name, f.name) and (
                self.confidence(g.name, f.name) < threshold or self.is_contradictory(g.name, f.name)
            ):
                out.append((g.name, f.name))
        return out

    # ------------------------------------------------------- collected values for use
    def collected(self, group: str, name: str) -> list[Any]:
        """All accepted values of a field as a flat list (multi fields merge sources)."""
        spec = schema.field_spec(group, name)
        vals = self.field_values(group, name)
        if not vals:
            return []
        if spec.multi:
            out: list[Any] = []
            seen: set[str] = set()
            vals = sorted(vals, key=lambda v: (not v.preferred, v.source_type != "user", -v.confidence))
            for v in vals:
                items = v.value if isinstance(v.value, list) else [v.value]
                for item in items:
                    k = _key(item)
                    if k not in seen:
                        seen.add(k)
                        out.append(item)
            return out
        p = self.preferred(group, name)
        return [p.value] if p else []

    def display_value(self, group: str, name: str) -> Any:
        spec = schema.field_spec(group, name)
        if spec.multi:
            return self.collected(group, name)
        p = self.preferred(group, name)
        return p.value if p else None

    # ------------------------------------------------------------------- export
    def to_json(self) -> dict[str, Any]:
        """The specification §2.8 shape, plus a ``provenance`` section with every envelope."""
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "iso639_3": self.iso639_3,
            "identifier_type": self.identifier_type,
        }
        prov: dict[str, Any] = {}
        for g in schema.GROUPS:
            block: dict[str, Any] = {}
            pblock: dict[str, Any] = {}
            for f in g.fields:
                block[f.name] = self.display_value(g.name, f.name) if not f.multi else self.collected(g.name, f.name)
                envs = [v.envelope() for v in self.field_values(g.name, f.name, include_proposed=True)]
                if envs:
                    pblock[f.name] = envs
            out[g.name] = block
            if pblock:
                prov[g.name] = pblock
        out["provenance"] = prov
        return out


def _key(value: Any) -> str:
    if isinstance(value, dict):
        return repr(sorted((k, _key(v)) for k, v in value.items()))
    if isinstance(value, list):
        return repr([_key(v) for v in value])
    return str(value).strip().lower()
