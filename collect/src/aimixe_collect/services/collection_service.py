"""Collection sessions and the discovery-mode runners (specification §3, §8, §10, §17)."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..discovery.candidate import CandidateResource, PipelineOutcome
from ..discovery.offline_scan import ScanReport, scan, scan_terms
from ..ingestion.pipeline import IngestionPipeline, PipelineContext
from ..profile.model import Profile

if TYPE_CHECKING:
    from .app import App


@dataclass
class SessionSummary:
    id: str
    language_id: str
    language_name: str
    mode: str
    status: str
    started_at: str
    finished_at: str | None
    discovered: int
    relevant: int
    downloaded: int
    duplicates: int
    failed: int
    pending_review: int


@dataclass
class RunResult:
    session_id: str
    outcomes: list[PipelineOutcome] = field(default_factory=list)
    scan_report: ScanReport | None = None


class CollectionService:
    MODES = ("Catalogue Search", "Agent Search", "Offline Collection", "Import")

    def __init__(self, app: "App"):
        self.app = app

    # ---------------------------------------------------------------- sessions
    def start_session(self, profile: Profile, mode: str, params: dict | None = None) -> str:
        sid = self.app.sessions.create(profile.id, mode, params)
        self.app.sessions.event(sid, "info", f"session started: {mode}", params)
        self.app.log.write("session.start", session=sid, language=profile.id, mode=mode)
        return sid

    def finish_session(self, session_id: str, status: str = "finished") -> SessionSummary:
        self.app.sessions.finish(session_id, status)
        self.app.log.write("session.finish", session=session_id, status=status)
        return self.summary(session_id)

    def summary(self, session_id: str) -> SessionSummary:
        r = self.app.sessions.get(session_id)
        lang = self.app.languages.get(r["language_id"])
        return SessionSummary(
            id=r["id"], language_id=r["language_id"], language_name=lang["name"] if lang else r["language_id"],
            mode=r["mode"], status=r["status"], started_at=r["started_at"], finished_at=r["finished_at"],
            discovered=r["discovered"], relevant=r["relevant"], downloaded=r["downloaded"],
            duplicates=r["duplicates"], failed=r["failed"], pending_review=r["pending_review"])

    def pipeline(self, profile: Profile, session_id: str | None) -> IngestionPipeline:
        ctx = PipelineContext(config=self.app.config, profile=profile, session_id=session_id,
                              resources=self.app.resources, sessions=self.app.sessions,
                              reviews=self.app.reviews, store=self.app.store, log=self.app.log)
        return IngestionPipeline(ctx)

    def ingest(self, profile: Profile, session_id: str, cand: CandidateResource) -> PipelineOutcome:
        self.app.sessions.bump(session_id, "discovered")
        return self.pipeline(profile, session_id).run(cand)

    # ---------------------------------------------------------------- offline
    def offline_terms(self, profile: Profile) -> list:
        return scan_terms(profile)

    def run_offline(self, profile: Profile, roots: list[Path], storage_mode: str | None = None,
                    on_outcome: Callable[[PipelineOutcome], None] | None = None,
                    on_progress: Callable[[int, Path, int], None] | None = None,
                    content_scan: bool | None = None) -> RunResult:
        sid = self.start_session(profile, "Offline Collection",
                                 {"roots": [str(r) for r in roots], "storage_mode": storage_mode,
                                  "content_scan": content_scan})
        result = RunResult(session_id=sid)
        pipe = self.pipeline(profile, sid)
        excl = list(self.app.config.get("scan", "exclude_dirs", []))
        report: ScanReport | None = None
        try:
            content = bool(self.app.config.get("scan", "content", True)) if content_scan is None else content_scan
            for cand, report in scan(profile, roots, excl, progress=on_progress, content=content,
                                     content_max_bytes=int(self.app.config.get("scan", "content_max_mb", 20)) * 1024 * 1024):
                if cand is None:
                    continue
                if storage_mode:
                    cand.import_method = storage_mode
                self.app.sessions.bump(sid, "discovered")
                out = pipe.run(cand)
                result.outcomes.append(out)
                if on_outcome:
                    on_outcome(out)
            status = "finished"
        except KeyboardInterrupt:
            status = "interrupted"
        result.scan_report = report
        if report is not None:
            self.app.sessions.event(sid, "info", "scan complete",
                                    {"files_seen": report.files_seen, "hits": report.hits,
                                     "dirs_skipped": report.dirs_skipped, "terms": len(report.terms)})
        self.finish_session(sid, status)
        return result

    # ---------------------------------------------------------------- listing
    def resources_for(self, profile: Profile):
        return self.app.resources.for_language(profile.id)

    def resource_sources(self, resource_id: int):
        return self.app.resources.sources(resource_id)

    def iter_candidates(self, profile: Profile, session_id: str,
                        candidates: Iterator[CandidateResource]) -> Iterator[PipelineOutcome]:
        pipe = self.pipeline(profile, session_id)
        for cand in candidates:
            self.app.sessions.bump(session_id, "discovered")
            yield pipe.run(cand)
