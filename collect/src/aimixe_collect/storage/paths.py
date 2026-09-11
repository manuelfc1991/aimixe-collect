"""The ``~/.aimixe`` directory layout (specification §11)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Category folders under languages/<id>/resources/, in specification order.
RESOURCE_CATEGORIES = (
    "documents",
    "text",
    "dictionaries",
    "corpora",
    "audio",
    "video",
    "images",
    "archives",
    "other",
)


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def catalogues(self) -> Path:
        return self.root / "catalogues"

    @property
    def search_engines(self) -> Path:
        return self.root / "search-engines"

    @property
    def database_dir(self) -> Path:
        return self.root / "database"

    @property
    def database(self) -> Path:
        return self.database_dir / "aimixe.db"

    @property
    def languages(self) -> Path:
        return self.root / "languages"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def temp(self) -> Path:
        return self.root / "temp"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def ensure(self) -> None:
        for d in (self.config, self.catalogues, self.search_engines, self.database_dir, self.languages,
                  self.cache, self.temp, self.logs):
            d.mkdir(parents=True, exist_ok=True)

    # --- per-language ---------------------------------------------------------------

    def language_dir(self, language_id: str) -> Path:
        return self.languages / safe_id(language_id)

    def language_json(self, language_id: str) -> Path:
        return self.language_dir(language_id) / "language.json"

    def resources_dir(self, language_id: str, category: str = "") -> Path:
        base = self.language_dir(language_id) / "resources"
        return base / category if category else base

    def extracted_dir(self, language_id: str) -> Path:
        return self.language_dir(language_id) / "extracted"

    def metadata_dir(self, language_id: str) -> Path:
        return self.language_dir(language_id) / "metadata"

    def manifests_dir(self, language_id: str) -> Path:
        return self.language_dir(language_id) / "manifests"

    def ensure_language(self, language_id: str) -> Path:
        base = self.language_dir(language_id)
        for cat in RESOURCE_CATEGORIES:
            self.resources_dir(language_id, cat).mkdir(parents=True, exist_ok=True)
        for d in (self.extracted_dir(language_id), self.metadata_dir(language_id),
                  self.manifests_dir(language_id)):
            d.mkdir(parents=True, exist_ok=True)
        return base


def safe_id(value: str) -> str:
    """A language id as a folder name: lowercase, only ``[a-z0-9_-]``."""
    out = []
    for ch in value.strip().lower():
        out.append(ch if (ch.isalnum() or ch in "-_") else "-")
    return "".join(out).strip("-") or "unknown"
