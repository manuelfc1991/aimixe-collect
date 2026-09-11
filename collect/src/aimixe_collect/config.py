"""Configuration and home-directory bootstrap.

The module lives under ``~/.aimixe`` (override with ``AIMIXE_HOME``). Configuration is a
TOML file at ``~/.aimixe/config/config.toml``; every key has a default so the file may be
absent. Nothing here touches the network or a database.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .storage.paths import Paths

DEFAULT_CONFIG: dict[str, Any] = {
    "general": {
        # Confidence below this counts as "uncertain" and is re-asked in the profile wizard.
        "uncertain_below": 0.6,
        # Default storage mode for import and offline collection: copy | move | reference.
        "storage_mode": "copy",
    },
    "relevance": {
        "confirmed_at": 70,
        "review_at": 30,
    },
    "agent": {
        # Agent provider: rule_based (no model) | claude | codex | gemini | agy | qwen | ollama | llm | custom.
        # A custom or overridden command goes in [agent.cli]: command = "tool --flag {prompt}".
        "provider": "rule_based",
        # Web search backends for Agent Search, in order. Built in: duckduckgo, bing, wikipedia.
        # A keyed JSON search API can be added as [agent.search_api] with url/items/fields.
        "search_backends": ["duckduckgo", "bing", "wikipedia"],
        "max_queries": 16,
        "hits_per_query": 8,
        "max_pages": 40,
        "max_depth": 2,
        "per_host": 6,
        "max_rounds": 2,
        "max_files": 40,
    },
    "online": {
        "max_download_mb": 500,
        "max_results_per_provider": 25,
        "max_files_per_record": 25,
        # Non-interactive runs (--yes) download results scoring at least this.
        "min_download_score": 50,
        # Files downloaded at the same time during Catalogue Search (storage stays sequential).
        "parallel_downloads": 3,
        "timeout": 30,
        # Disabled catalogue providers (by name); `aimixe collect catalogue remove` maintains this.
        "disabled_catalogues": [],
    },
    "extraction": {
        # Optional content extraction stage (§10): text.txt / metadata.json / pages.json under extracted/.
        "enabled": True,
        "max_text_mb": 50,
    },
    "archives": {
        # Ingest the members of ZIP/TAR archives as resources of their own (the archive is kept too).
        "ingest_members": False,
        "max_members": 200,
    },
    "dedup": {
        # Near-duplicate detection on extracted text (MinHash); pairs at or above the threshold are linked.
        "fuzzy": True,
        "threshold": 0.85,
    },
    "scan": {
        # Directories never scanned during Offline Collection.
        "exclude_dirs": [".git", "node_modules", "__pycache__", ".cache", ".venv", "venv"],
        "max_file_size_mb": 4096,
        # Offline Collection also looks inside text-bearing files up to this size (name matches are always used).
        "content": True,
        "content_max_mb": 20,
    },
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


@dataclass
class Config:
    paths: Paths
    values: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_CONFIG))

    def get(self, section: str, key: str, default: Any = None) -> Any:
        return self.values.get(section, {}).get(key, default)

    @property
    def uncertain_below(self) -> float:
        return float(self.get("general", "uncertain_below", 0.6))

    @property
    def storage_mode(self) -> str:
        return str(self.get("general", "storage_mode", "copy"))

    @property
    def confirmed_at(self) -> int:
        return int(self.get("relevance", "confirmed_at", 70))

    @property
    def review_at(self) -> int:
        return int(self.get("relevance", "review_at", 30))


def home_dir() -> Path:
    env = os.environ.get("AIMIXE_HOME")
    return Path(env).expanduser() if env else Path.home() / ".aimixe"


def bootstrap(root: Path | None = None) -> Config:
    """Create the ``~/.aimixe`` tree if needed and load configuration."""
    paths = Paths(root or home_dir())
    paths.ensure()
    values = dict(DEFAULT_CONFIG)
    cfg_file = paths.config / "config.toml"
    if cfg_file.exists():
        with cfg_file.open("rb") as fh:
            values = _merge(values, tomllib.load(fh))
    else:
        cfg_file.write_text(_default_config_text(), encoding="utf-8")
    return Config(paths=paths, values=values)


def _default_config_text() -> str:
    return (
        "# AImixE Data Collection Module configuration.\n"
        "# Every key is optional; the defaults are shown.\n\n"
        "[general]\n"
        "uncertain_below = 0.6\n"
        'storage_mode = "copy"   # copy | move | reference\n\n'
        "[relevance]\n"
        "confirmed_at = 70\n"
        "review_at = 30\n\n"
        "[agent]\n"
        'provider = "rule_based"   # rule_based | claude | codex | gemini | agy | qwen | ollama | llm | custom\n'
        'search_backends = ["duckduckgo", "bing", "wikipedia"]\n'
        "max_queries = 16\n"
        "hits_per_query = 8\n"
        "max_pages = 40\n"
        "max_depth = 2\n"
        "per_host = 6\n"
        "max_rounds = 2\n"
        "max_files = 40\n"
        '# [agent.cli]\n# command = "my_tool --quiet {prompt}"\n\n'
        "[online]\n"
        "max_download_mb = 500\n"
        "max_results_per_provider = 25\n"
        "max_files_per_record = 25\n"
        "min_download_score = 50\n"
        "parallel_downloads = 3\n"
        "timeout = 30\n"
        "disabled_catalogues = []\n\n"
        "[extraction]\n"
        "enabled = true\n"
        "max_text_mb = 50\n\n"
        "[archives]\n"
        "ingest_members = false\n"
        "max_members = 200\n\n"
        "[dedup]\n"
        "fuzzy = true\n"
        "threshold = 0.85\n\n"
        "[scan]\n"
        'exclude_dirs = [".git", "node_modules", "__pycache__", ".cache", ".venv", "venv"]\n'
        "max_file_size_mb = 4096\n"
        "content = true\n"
        "content_max_mb = 20\n"
    )
