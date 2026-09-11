"""Language resolution (specification §1).

Order: local registry first, then the bundled ISO / Glottolog tables. Accepts a language
name, an ISO 639-3 code, a known alternative name or a known dialect/alias.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .local_registry import LocalMatch, LocalRegistry
from .registry import Candidate, LanguageRecord, Registry


@dataclass
class ResolvedLanguage:
    """One candidate the user can confirm."""
    language_id: str
    name: str
    iso639_3: str | None
    identifier_type: str            # iso | local
    matched_on: str
    matched_text: str
    score: float
    source: str                     # local_registry | bundled
    record: LanguageRecord | None = None
    alternative_names: list[str] = field(default_factory=list)
    region: str = ""


@dataclass
class Resolution:
    query: str
    status: str                     # exact | ambiguous | none
    matches: list[ResolvedLanguage] = field(default_factory=list)

    @property
    def best(self) -> ResolvedLanguage | None:
        return self.matches[0] if self.matches else None


class LanguageResolver:
    def __init__(self, registry: Registry, local: LocalRegistry):
        self.registry = registry
        self.local = local

    def _from_local(self, m: LocalMatch) -> ResolvedLanguage:
        rec = self.registry.by_code(m.iso639_3) if m.iso639_3 else None
        return ResolvedLanguage(
            language_id=m.language_id, name=m.name, iso639_3=m.iso639_3,
            identifier_type="iso" if m.iso639_3 else "local",
            matched_on=m.matched_on, matched_text=m.matched_text, score=m.score,
            source="local_registry", record=rec,
            alternative_names=rec.alternative_names()[:8] if rec else [],
            region=self.registry.region_text(rec) if rec else "",
        )

    def _from_bundled(self, c: Candidate) -> ResolvedLanguage:
        rec = c.record
        name = rec.display_name
        alts = rec.alternative_names()
        if c.matched_on == "alternate_name":
            # the user's own name for the language leads; the ISO reference name stays reachable
            name = c.matched_text
            alts = [rec.display_name] + [a for a in alts if a.lower() != name.lower()]
        return ResolvedLanguage(
            language_id=rec.code, name=name, iso639_3=rec.code,
            identifier_type="iso", matched_on=c.matched_on, matched_text=c.matched_text,
            score=c.score, source="bundled", record=rec,
            alternative_names=alts[:8],
            region=self.registry.region_text(rec),
        )

    def resolve(self, query: str) -> Resolution:
        query = (query or "").strip()
        if not query:
            return Resolution(query=query, status="none")
        matches: list[ResolvedLanguage] = []
        seen: set[str] = set()

        for m in self.local.find(query):
            r = self._from_local(m)
            matches.append(r)
            seen.add(r.language_id)
            if r.iso639_3:
                seen.add(r.iso639_3)

        for c in self.registry.find(query):
            if c.record.code in seen:
                continue
            seen.add(c.record.code)
            matches.append(self._from_bundled(c))

        if not matches:
            return Resolution(query=query, status="none")
        best = matches[0]
        strong = [m for m in matches if m.score >= 0.9]
        if best.source == "local_registry" and best.score >= 0.85:
            return Resolution(query=query, status="exact", matches=matches)
        if best.score >= 0.98 and len(strong) == 1:
            return Resolution(query=query, status="exact", matches=matches)
        if len(strong) == 1 and best.matched_on in ("alternate_name", "code", "name"):
            return Resolution(query=query, status="exact", matches=matches)
        return Resolution(query=query, status="ambiguous", matches=matches)
