"""Catalogue providers: list / add / remove, and the Catalogue Search run (specification §4.1)."""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..catalogues import http
from ..catalogues.base import CatalogueProvider, CatalogueResult
from ..catalogues.registry import KINDS, ProviderEntry, ProviderRegistry, build_provider
from ..discovery.candidate import PipelineOutcome
from ..discovery.catalogue_search import CatalogueRunReport, collect_results, search_all, write_lookup_manifest
from ..profile.model import Profile
from ..progress import Progress

if TYPE_CHECKING:
    from .app import App


@dataclass
class CatalogueRun:
    session_id: str
    report: CatalogueRunReport
    outcomes: list[PipelineOutcome] = field(default_factory=list)
    lookup_manifest: Path | None = None


class CatalogueService:
    def __init__(self, app: "App"):
        self.app = app
        http.configure_cache(app.paths.cache / "http")
        self.registry = ProviderRegistry(app.paths.catalogues, disabled=set(self._disabled()))

    # ---------------------------------------------------------------- management
    def _disabled(self) -> list[str]:
        return list(self.app.config.get("online", "disabled_catalogues", []) or [])

    def list(self) -> list[ProviderEntry]:
        return self.registry.list()

    def enabled(self) -> list[CatalogueProvider]:
        return self.registry.enabled()

    def get(self, name: str) -> ProviderEntry | None:
        return self.registry.get(name)

    def add(self, cfg: dict[str, Any]) -> Path:
        """Validate a provider configuration and write it to ~/.aimixe/catalogues/<name>.toml."""
        name = re.sub(r"[^a-z0-9_-]+", "_", str(cfg.get("name", "")).strip().lower()).strip("_")
        if not name:
            raise ValueError("a catalogue needs a name")
        cfg = dict(cfg, name=name)
        build_provider(cfg)                       # raises ValueError when the shape is wrong
        path = self.app.paths.catalogues / f"{name}.toml"
        path.write_text(_to_toml(cfg), encoding="utf-8")
        self.registry.reload()
        self.app.log.write("catalogue.add", name=name, path=str(path))
        return path

    def remove(self, name: str) -> str:
        """Delete a user catalogue file, or disable a built-in one. Returns what happened."""
        entry = self.registry.get(name)
        if entry is None:
            raise ValueError(f"no catalogue named {name!r}")
        if entry.source != "builtin":
            Path(entry.source).unlink(missing_ok=True)
            self.registry.reload()
            self.app.log.write("catalogue.remove", name=name)
            return f"removed {entry.source}"
        disabled = self._disabled()
        if name not in disabled:
            disabled.append(name)
            self._write_disabled(disabled)
        self.registry.disabled = set(disabled)
        self.registry.reload()
        self.app.log.write("catalogue.disable", name=name)
        return f"built-in catalogue {name} disabled (re-enable by editing disabled_catalogues in config.toml)"

    def _write_disabled(self, names: list[str]) -> None:
        cfg = self.app.paths.config / "config.toml"
        text = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
        line = "disabled_catalogues = [" + ", ".join(f'"{n}"' for n in names) + "]"
        if re.search(r"^disabled_catalogues\s*=", text, re.M):
            text = re.sub(r"^disabled_catalogues\s*=.*$", line, text, flags=re.M)
        elif "[online]" in text:
            text = text.replace("[online]", f"[online]\n{line}", 1)
        else:
            text += f"\n[online]\n{line}\n"
        cfg.write_text(text, encoding="utf-8")
        self.app.config.values.setdefault("online", {})["disabled_catalogues"] = names

    # ---------------------------------------------------------------- search
    def search(self, profile: Profile, providers: list[CatalogueProvider] | None = None,
               on_provider: Callable[[str, int], None] | None = None) -> CatalogueRunReport:
        providers = providers if providers is not None else self.enabled()
        return search_all(providers, profile, review_at=self.app.config.review_at,
                          confirmed_at=self.app.config.confirmed_at,
                          limit_per_provider=int(self.app.config.get("online", "max_results_per_provider", 25)),
                          on_provider=on_provider)

    def collect(self, profile: Profile, report: CatalogueRunReport, *, min_score: int | None = None,
                on_outcome: Callable[[PipelineOutcome], None] | None = None,
                on_message: Callable[[str], None] | None = None,
                progress: Progress | None = None) -> CatalogueRun:
        """Download and ingest the report's results at or above ``min_score`` in one session."""
        col = self.app.collection_service
        sid = col.start_session(profile, "Catalogue Search",
                                {"providers": report.providers, "min_score": min_score})
        run = CatalogueRun(session_id=sid, report=report)
        threshold = self.app.config.review_at if min_score is None else min_score
        for sr in report.results:
            if sr.action == "download" and sr.relevance.score < threshold:
                sr.action = "skip"
        self.app.sessions.bump(sid, "discovered", len(report.results) + len(report.lookups))
        for sr in report.results:
            if sr.action == "skip":
                self.app.sessions.event(sid, "info", f"skipped ({sr.relevance.score}): {sr.result.title[:80]}",
                                        {"url": sr.result.landing_url, "reasons": sr.relevance.reasons})
        providers = {e.provider.name: e.provider for e in self.registry.list()}
        pipe = col.pipeline(profile, sid)
        temp = self.app.paths.temp / f"download-{sid}"
        try:
            run.outcomes = collect_results(
                report, providers, profile, sid, temp, pipe.run,
                max_bytes=int(self.app.config.get("online", "max_download_mb", 500)) * 1024 * 1024,
                max_files=int(self.app.config.get("online", "max_files_per_record", 25)),
                workers=int(self.app.config.get("online", "parallel_downloads", 3)), progress=progress,
                propose=lambda r: self._propose(profile, r, sid), on_outcome=on_outcome, on_message=on_message)
            status = "finished"
        except KeyboardInterrupt:
            status = "interrupted"
        for r in report.lookups:
            self.app.sessions.event(sid, "info", f"lookup: {r.title[:80]}", {"url": r.landing_url})
        run.lookup_manifest = write_lookup_manifest(self.app.paths.manifests_dir(profile.id), sid, report)
        for note in report.notes:
            self.app.sessions.event(sid, "info", note)
        for err in report.errors:
            self.app.sessions.event(sid, "error", err)
            self.app.sessions.bump(sid, "failed")
        try:
            for leftover in temp.glob("*"):
                leftover.unlink()
            temp.rmdir()
        except OSError:
            pass
        col.finish_session(sid, status)
        return run

    def _propose(self, profile: Profile, r: CatalogueResult, session_id: str) -> int:
        """Catalogue-asserted language facts go to the review queue unless already known."""
        n = 0
        for prop in r.proposals:
            if profile.is_known(prop.group, prop.field):
                current = profile.collected(prop.group, prop.field)
                if prop.value in current or (isinstance(prop.value, list) and all(v in current for v in prop.value)):
                    continue
                if not isinstance(prop.value, (list, dict)) and any(
                        str(prop.value).lower() == str(c).lower() for c in current):
                    continue
            self.app.review_service.propose_profile_field(profile, prop.group, prop.field, prop.value,
                                                          prop.confidence, prop.source, source_type="catalogue",
                                                          session_id=session_id)
            self.app.sessions.bump(session_id, "pending_review")
            n += 1
        return n


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def _to_toml(cfg: dict[str, Any]) -> str:
    lines = ["# User catalogue provider for aimixe collect. Edit freely; kinds: " + ", ".join(KINDS), ""]
    tables = {}
    for k, v in cfg.items():
        if k == "builtin":
            continue
        if isinstance(v, dict):
            tables[k] = v
        else:
            lines.append(f"{k} = {_toml_value(v)}")
    for t, d in tables.items():
        lines.append(f"\n[{t}]")
        for k, v in d.items():
            lines.append(f"{k} = {_toml_value(v)}")
    return "\n".join(lines) + "\n"
