"""Catalogue provider interface (specification §4.1).

Every provider exposes ``search(language_profile)``, ``fetch(result)``,
``extract_metadata(result)`` and ``download(resource)``. Providers receive the complete
profile and may use any of its fields to build queries.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..profile.model import Profile
from ..relevance.scorer import ProfileTerms, terms_from_profile


@dataclass
class DownloadableFile:
    url: str
    filename: str | None = None
    size: int | None = None
    format: str | None = None


@dataclass
class ProfileProposal:
    """A language fact a catalogue asserts; it reaches the profile only through review (§18)."""
    group: str
    field: str
    value: Any
    confidence: float
    source: str


@dataclass
class CatalogueResult:
    provider: str
    kind: str                                   # record | lookup
    title: str
    landing_url: str | None = None              # page a person can open (source URL)
    description: str | None = None
    language: str | None = None                 # the catalogue's own language field
    date: str | None = None
    licence: str | None = None
    types: list[str] = field(default_factory=list)      # catalogue's classification hints
    identifiers: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    files: list[DownloadableFile] = field(default_factory=list)
    query: str | None = None
    proposals: list[ProfileProposal] = field(default_factory=list)
    fetched: bool = False

    @property
    def key(self) -> str:
        return self.landing_url or f"{self.provider}:{self.title}"

    def text_for_relevance(self) -> str:
        bits = [self.title or "", self.description or "", self.language or "", " ".join(self.types)]
        for k, v in self.metadata.items():
            if isinstance(v, str) and len(v) < 500:
                bits.append(f"{k} {v}")
            elif isinstance(v, list):
                bits.extend(str(x) for x in v[:20] if isinstance(x, (str, int)))
        return " ".join(bits)


@dataclass
class SearchQuery:
    text: str
    basis: str          # name | code | alternate_name | variety | publication | translation


class CatalogueProvider:
    """Base class. Subclasses set ``name`` and implement ``search``; the rest has defaults."""

    name: str = "provider"
    description: str = ""
    kind: str = "record"            # record: returns fetchable records · lookup: returns a URL to open
    asks_by: str = "name"           # name | code | both
    needs_code: bool = False
    licence_note: str = ""
    homepage: str = ""
    builtin: bool = True

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    # ---------------------------------------------------------------- queries
    def queries(self, profile: Profile, terms: ProfileTerms | None = None, limit: int = 6) -> list[SearchQuery]:
        """Search strings derived from the whole profile, most specific first."""
        t = terms or terms_from_profile(profile)
        out: list[SearchQuery] = []
        seen: set[str] = set()

        def add(text: str, basis: str) -> None:
            k = text.strip().lower()
            if k and k not in seen and len(out) < limit:
                seen.add(k)
                out.append(SearchQuery(text.strip(), basis))

        if self.asks_by in ("code", "both") and t.iso:
            add(t.iso, "code")
        if self.asks_by in ("name", "both"):
            add(t.name, "name")
            for a in t.alternate_names[:3]:
                add(a if " " in a.strip() else f"{a} language", "alternate_name")
            for v in t.varieties[:2]:
                add(v, "variety")
            for pub in t.publications[:2]:
                add(pub, "publication")
            for tr in t.translations[:1]:
                add(tr, "translation")
        return out

    # ---------------------------------------------------------------- interface
    def search(self, language_profile: Profile, limit: int = 25) -> list[CatalogueResult]:
        raise NotImplementedError

    def fetch(self, result: CatalogueResult) -> CatalogueResult:
        """Complete a result (e.g. list its files). Default: nothing more to fetch."""
        result.fetched = True
        return result

    def extract_metadata(self, result: CatalogueResult) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "title": result.title, "description": result.description, "language": result.language,
            "date": result.date, "licence": result.licence, "catalogue": self.name,
            "landing_url": result.landing_url,
        }
        meta.update({k: v for k, v in result.identifiers.items()})
        for k, v in result.metadata.items():
            if isinstance(v, (str, int, float)) and k not in meta:
                meta[k] = v
        return {k: v for k, v in meta.items() if v not in (None, "", [], {})}

    def download(self, resource: DownloadableFile, dest_dir: Path, max_bytes: int, progress=None) -> Path:
        from .http import download_file
        return download_file(resource.url, dest_dir, filename=resource.filename, max_bytes=max_bytes, progress=progress)

    def available_for(self, profile: Profile) -> tuple[bool, str]:
        if self.needs_code and not profile.iso639_3:
            return False, f"{self.name} needs an ISO 639-3 code and this language has none"
        return True, ""

    def describe(self) -> str:
        return f"{self.name:18} {self.kind:7} {self.description}"
