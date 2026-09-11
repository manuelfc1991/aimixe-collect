"""Duplicate detection (specification §13). Exact SHA-256 now; a fuzzy slot for Phase 4."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..db.repositories import ResourceRepo, ResourceRow


@dataclass
class DuplicateCheck:
    exact: ResourceRow | None            # an existing resource with the same SHA-256
    fuzzy: list[tuple[int, float]]       # (resource_id, similarity) — Phase 4


class DuplicateDetector:
    def __init__(self, resources: ResourceRepo):
        self.resources = resources

    def check(self, sha256: str, path: Path | None = None) -> DuplicateCheck:
        return DuplicateCheck(exact=self.resources.by_hash(sha256), fuzzy=self.fuzzy(path))

    def fuzzy(self, path: Path | None) -> list[tuple[int, float]]:
        """Near-duplicate detection hook. Implemented in Phase 4 (MinHash / perceptual hash)."""
        return []
