"""Provider registry: built-ins from ``data/builtin-catalogues.toml`` plus user TOML files."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib import resources as ilr
from pathlib import Path
from typing import Any

from .base import CatalogueProvider
from .builtin.dspace import DSpaceProvider
from .builtin.glottolog import GlottologProvider
from .builtin.internet_archive import InternetArchiveProvider
from .configurable import ConfigurableProvider

PYTHON_CLASSES: dict[str, type[CatalogueProvider]] = {
    "glottolog": GlottologProvider,
    "internet_archive": InternetArchiveProvider,
    "dspace": DSpaceProvider,
}

KINDS = ("lookup", "api_json", "html_links", "python")


@dataclass
class ProviderEntry:
    name: str
    provider: CatalogueProvider
    source: str            # builtin | <path to user toml>
    enabled: bool = True


def build_provider(cfg: dict[str, Any]) -> CatalogueProvider:
    kind = cfg.get("kind", "lookup")
    if kind not in KINDS:
        raise ValueError(f"catalogue {cfg.get('name')!r}: unknown kind {kind!r} (use one of {', '.join(KINDS)})")
    if kind == "python":
        cls = PYTHON_CLASSES.get(cfg.get("class", ""))
        if cls is None:
            raise ValueError(f"catalogue {cfg.get('name')!r}: unknown class {cfg.get('class')!r}")
        p = cls(cfg)
        p.name = cfg.get("name", p.name)
        return p
    if "url" not in cfg:
        raise ValueError(f"catalogue {cfg.get('name')!r}: 'url' is required")
    return ConfigurableProvider(cfg)


def load_builtin_configs() -> list[dict[str, Any]]:
    text = ilr.files("aimixe_collect.data").joinpath("builtin-catalogues.toml").read_text(encoding="utf-8")
    return [dict(c, builtin=True) for c in tomllib.loads(text).get("catalogue", [])]


def load_user_configs(directory: Path) -> list[tuple[Path, dict[str, Any]]]:
    out = []
    if not directory.exists():
        return out
    for f in sorted(directory.glob("*.toml")):
        try:
            data = tomllib.loads(f.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        cats = data.get("catalogue")
        if isinstance(cats, list):
            for c in cats:
                out.append((f, c))
        elif "name" in data:
            out.append((f, data))
    return out


class ProviderRegistry:
    def __init__(self, user_dir: Path, disabled: set[str] | None = None):
        self.user_dir = user_dir
        self.disabled = disabled or set()
        self.entries: dict[str, ProviderEntry] = {}
        self.errors: list[str] = []
        self.reload()

    def reload(self) -> None:
        self.entries = {}
        self.errors = []
        for cfg in load_builtin_configs():
            self._add(cfg, "builtin")
        for path, cfg in load_user_configs(self.user_dir):
            self._add(cfg, str(path))   # a user entry with the same name overrides the built-in

    def _add(self, cfg: dict[str, Any], source: str) -> None:
        try:
            p = build_provider(cfg)
        except ValueError as exc:
            self.errors.append(str(exc))
            return
        self.entries[p.name] = ProviderEntry(p.name, p, source, enabled=p.name not in self.disabled)

    def enabled(self) -> list[CatalogueProvider]:
        return [e.provider for e in self.entries.values() if e.enabled]

    def get(self, name: str) -> ProviderEntry | None:
        return self.entries.get(name)

    def list(self) -> list[ProviderEntry]:
        return list(self.entries.values())
