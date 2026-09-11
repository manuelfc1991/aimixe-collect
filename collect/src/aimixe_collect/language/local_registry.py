"""The locally stored language registry: profiles already under ``~/.aimixe/languages``.

Searched *before* the bundled tables (specification §1). Indexes the primary name, ISO
code, alternative names, exonyms, varieties and community names of every stored profile.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .registry import fold


@dataclass
class LocalMatch:
    language_id: str
    name: str
    iso639_3: str | None
    matched_on: str
    matched_text: str
    score: float
    path: Path


class LocalRegistry:
    def __init__(self, languages_dir: Path):
        self.languages_dir = languages_dir

    def profiles(self) -> list[dict]:
        out = []
        if not self.languages_dir.exists():
            return out
        for lang_dir in sorted(self.languages_dir.iterdir()):
            f = lang_dir / "language.json"
            if f.is_file():
                try:
                    out.append(json.loads(f.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    continue
        return out

    @staticmethod
    def _values(profile: dict, group: str, field: str) -> list[str]:
        raw = (profile.get(group) or {}).get(field)
        if raw is None:
            return []
        if isinstance(raw, list):
            vals = []
            for v in raw:
                if isinstance(v, dict):
                    vals.append(str(v.get("name") or v.get("value") or ""))
                else:
                    vals.append(str(v))
            return [v for v in vals if v]
        if isinstance(raw, dict):
            return [str(raw.get("value") or raw.get("name") or "")]
        return [str(raw)]

    def find(self, query: str) -> list[LocalMatch]:
        fq = fold(query)
        if not fq:
            return []
        out: list[LocalMatch] = []
        for p in self.profiles():
            lid = p.get("id") or ""
            name = p.get("name") or lid
            iso = p.get("iso639_3")
            path = self.languages_dir / lid / "language.json"
            checks: list[tuple[str, str, float]] = [("name", name, 1.0)]
            if iso:
                checks.append(("code", iso, 1.0))
            if lid:
                checks.append(("code", lid, 0.99))
            for v in self._values(p, "identity", "alternate_names"):
                checks.append(("alternate_name", v, 0.92))
            for v in self._values(p, "identity", "exonyms"):
                checks.append(("exonym", v, 0.9))
            for v in self._values(p, "orthography_location", "varieties"):
                checks.append(("variety", v, 0.85))
            for kind, text, score in checks:
                if fold(text) == fq:
                    out.append(LocalMatch(lid, name, iso, kind, text, score, path))
                    break
        out.sort(key=lambda m: -m.score)
        return out
