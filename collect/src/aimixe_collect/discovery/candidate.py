"""A candidate resource: what every discovery mechanism hands to the shared pipeline (§10)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..logging_setup import now_iso

METHODS = ("catalogue", "agent", "offline", "import")


@dataclass
class CandidateResource:
    language_id: str
    method: str                                 # catalogue | agent | offline | import
    local_path: Path | None = None              # file already on disk (import, offline, downloaded)
    url: str | None = None                      # remote resource (online methods)
    title: str | None = None
    # discovery provenance (§16)
    source_url: str | None = None
    catalogue: str | None = None
    query: str | None = None
    discovery_date: str = field(default_factory=now_iso)
    download_date: str | None = None
    licence: str | None = None
    original_path: str | None = None
    detection_method: str | None = None
    detection_confidence: float | None = None
    import_method: str | None = None            # copy | move | reference
    # hints from the discoverer
    matched_terms: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    catalogue_types: list[str] = field(default_factory=list)   # resource types the catalogue claims (a relevance signal)
    type_hints: list[str] = field(default_factory=list)        # classification hints only; never relevance evidence
    user_asserted: bool = False                 # import: the user says this belongs to the language
    synthetic: bool = False                     # a record this module wrote itself (e.g. catalogue metadata JSON)

    def __post_init__(self) -> None:
        if self.method not in METHODS:
            raise ValueError(f"unknown discovery method {self.method!r}")

    @property
    def display(self) -> str:
        if self.title:
            return self.title
        if self.local_path:
            return self.local_path.name
        return self.url or "?"


@dataclass
class PipelineOutcome:
    status: str                     # stored | duplicate_linked | uncertain_review | rejected | failed
    candidate: CandidateResource
    resource_id: int | None = None
    sha256: str | None = None
    relevance: int | None = None
    band: str | None = None
    reasons: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)
    message: str = ""
