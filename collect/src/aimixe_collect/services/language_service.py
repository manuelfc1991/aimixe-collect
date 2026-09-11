"""Language resolution, creation and loading (specification §1)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..language.resolver import ResolvedLanguage, Resolution
from ..profile.enrich import enrich_from_registry
from ..profile.model import Profile
from ..storage.paths import safe_id

if TYPE_CHECKING:
    from .app import App


class LanguageService:
    def __init__(self, app: "App"):
        self.app = app

    def resolve(self, query: str) -> Resolution:
        return self.app.resolver.resolve(query)

    def exists(self, language_id: str) -> bool:
        return self.app.languages.get(language_id) is not None

    def list_languages(self):
        return self.app.languages.list()

    def load(self, language_id: str) -> Profile | None:
        row = self.app.languages.get(language_id)
        if row is None:
            return None
        profile = Profile(id=row["id"], name=row["name"], iso639_3=row["iso639_3"],
                          identifier_type=row["identifier_type"])
        return self.app.profiles.load(profile)

    def open_from_resolution(self, chosen: ResolvedLanguage) -> tuple[Profile, bool]:
        """Load the stored profile for a confirmed choice, or create it. Returns (profile, created)."""
        existing = self.load(chosen.language_id)
        if existing is not None:
            return existing, False
        name = chosen.name   # the resolver already prefers the name the user typed
        profile = Profile(id=chosen.language_id, name=name, iso639_3=chosen.iso639_3,
                          identifier_type=chosen.identifier_type)
        if chosen.record is not None:
            enrich_from_registry(profile, chosen.record, self.app.registry)
            ref = chosen.record.display_name
            if ref.lower() != name.lower():
                # keep the ISO reference name reachable as an alternative name
                alts = profile.collected("identity", "alternate_names")
                if ref not in alts:
                    from ..profile.model import FieldValue
                    profile.add("identity", "alternate_names",
                                FieldValue(value=[ref], source_type="local_database",
                                           source="ISO 639-3 reference name", confidence=0.9))
        self.save(profile)
        return profile, True

    def create_local(self, name: str, iso639_3: str | None = None) -> Profile:
        """A language not in any table: local identifier ``x-<slug>`` unless an ISO code is given."""
        if iso639_3 and self.app.registry.by_code(iso639_3):
            rec = self.app.registry.by_code(iso639_3)
            profile = Profile(id=rec.code, name=name, iso639_3=rec.code, identifier_type="iso")
            enrich_from_registry(profile, rec, self.app.registry)
        else:
            lid = "x-" + safe_id(name)
            profile = Profile(id=lid, name=name, iso639_3=None, identifier_type="local")
        self.save(profile)
        return profile

    def save(self, profile: Profile) -> None:
        self.app.languages.upsert(profile)
        self.app.profiles.save(profile)
        self.app.paths.ensure_language(profile.id)
        self.app.profile_service.write_language_json(profile)
        self.app.log.write("language.saved", language=profile.id)
