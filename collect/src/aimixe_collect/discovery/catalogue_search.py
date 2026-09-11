"""Catalogue Search runner (specification §4.1, §5, §7, §16).

For every enabled provider: search with the whole profile → score each result *before*
downloading → fetch file lists → download allowed files → hand each file to the shared
pipeline. Records without files are stored as metadata resources; lookup results are
written to a manifest and reported. Profile proposals go to the review queue.
"""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from ..catalogues import http
from ..catalogues.base import CatalogueProvider, CatalogueResult
from ..logging_setup import now_iso
from ..profile.model import Profile
from ..progress import Progress, human_bytes, human_rate, human_time
from ..relevance.scorer import ProfileTerms, RelevanceResult, score_text, terms_from_profile
from .candidate import CandidateResource, PipelineOutcome


@dataclass
class ScoredResult:
    result: CatalogueResult
    relevance: RelevanceResult
    action: str = ""            # download | metadata | lookup | skip


@dataclass
class CatalogueRunReport:
    providers: list[str] = field(default_factory=list)
    unavailable: dict[str, str] = field(default_factory=dict)
    results: list[ScoredResult] = field(default_factory=list)
    lookups: list[CatalogueResult] = field(default_factory=list)
    proposals: int = 0
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)      # informational, never counted as failures

    def by_action(self, action: str) -> list[ScoredResult]:
        return [s for s in self.results if s.action == action]


def score_result(terms: ProfileTerms, r: CatalogueResult) -> RelevanceResult:
    return score_text(terms, r.text_for_relevance(), metadata_language=r.language,
                      catalogue_types=r.types or None)


def search_all(providers: list[CatalogueProvider], profile: Profile, *, review_at: int, confirmed_at: int,
               limit_per_provider: int = 25,
               on_provider: Callable[[str, int], None] | None = None) -> CatalogueRunReport:
    """Search every provider and decide an action per result. Nothing is downloaded here."""
    terms = terms_from_profile(profile)
    report = CatalogueRunReport()
    seen: set[str] = set()
    for p in providers:
        ok, why = p.available_for(profile)
        if not ok:
            report.unavailable[p.name] = why
            continue
        report.providers.append(p.name)
        try:
            results = p.search(profile, limit=limit_per_provider)
        except Exception as exc:  # a broken provider must not stop the others
            report.errors.append(f"{p.name}: {type(exc).__name__}: {exc}")
            results = []
        n = 0
        for r in results:
            if r.key in seen:
                continue
            seen.add(r.key)
            n += 1
            if r.kind == "lookup":
                report.lookups.append(r)
                continue
            rel = score_result(terms, r)
            sr = ScoredResult(r, rel)
            if rel.score < review_at:
                sr.action = "skip"
            else:
                sr.action = "download"   # refined to metadata after fetch when no files exist
            report.results.append(sr)
        if on_provider:
            on_provider(p.name, n)
    report.results.sort(key=lambda s: -s.relevance.score)
    return report


def collect_results(report: CatalogueRunReport, providers: dict[str, CatalogueProvider], profile: Profile,
                    session_id: str, temp_dir: Path, ingest: Callable[[CandidateResource], PipelineOutcome],
                    *, max_bytes: int, max_files: int = 25, propose: Callable[[CatalogueResult], int] | None = None,
                    on_outcome: Callable[[PipelineOutcome], None] | None = None,
                    on_message: Callable[[str], None] | None = None, workers: int = 3,
                    progress: Progress | None = None) -> list[PipelineOutcome]:
    """Fetch, download and ingest everything the report marked for download.

    Downloads run ``workers`` at a time; storage (SQLite) stays sequential.
    """
    outcomes: list[PipelineOutcome] = []
    say = on_message or (lambda m: None)
    prog = progress or Progress()
    started = time.time()
    todo = [s for s in report.results if s.action == "download"]
    say(f"  {len(todo)} record(s) to fetch")
    total_bytes = 0
    for n, sr in enumerate(todo, 1):
        r = sr.result
        p = providers[r.provider]
        prog.step(record=n, records=len(todo), stage="fetching file list")
        say(f"  [{n}/{len(todo)}] {r.title[:70]}  ({r.provider}, relevance {sr.relevance.score})")
        try:
            p.fetch(r)
        except Exception as exc:
            report.errors.append(f"{p.name} fetch {r.title[:60]}: {exc}")
        meta = p.extract_metadata(r)
        if propose and r.proposals:
            report.proposals += propose(r)
        if not r.files:
            sr.action = "metadata"
            path = _write_metadata_record(temp_dir, r, meta)
            cand = _candidate(profile, r, path, meta, downloaded=False)
            cand.type_hints = ["metadata"]
            cand.synthetic = True
            out = ingest(cand)
            outcomes.append(out)
            if on_outcome:
                on_outcome(out)
            _cleanup(path)
            continue
        if len(r.files) > max_files:
            say(f"  {r.title[:60]}: {len(r.files)} files, downloading the first {max_files} "
                f"(raise online.max_files_per_record in config.toml for the rest)")
            report.notes.append(f"{r.provider}: {r.title[:60]} has {len(r.files)} files; {max_files} downloaded")
        wanted = []
        for f in r.files[:max_files]:
            if f.size and f.size > max_bytes:
                say(f"  skipped {f.filename or f.url.rsplit('/', 1)[-1]}: {f.size / 1e6:.0f} MB exceeds the "
                    f"{max_bytes / 1e6:.0f} MB cap (online.max_download_mb)")
                report.notes.append(f"{r.provider}: {f.url} skipped, {f.size} bytes over the cap")
                continue
            wanted.append(f)

        prog.step(stage="downloading", files=len(wanted), file=0)
        if wanted:
            say(f"      {len(wanted)} file(s)" + (f", {human_bytes(sum(x.size for x in wanted if x.size))} known size" if any(x.size for x in wanted) else ""))

        def fetch_one(item):
            i, f = item
            name = (f.filename or http.filename_from_response(f.url, None))[:60]
            key = f"{n}:{i}"
            prog.start(key, name, f.size)
            try:
                path = p.download(f, temp_dir, max_bytes, progress=prog.callback(key))
                prog.done(key, ok=True)
                return f, path, None
            except http.HttpError as exc:
                prog.done(key, ok=False, message=str(exc))
                return f, None, exc

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            for j, (f, path, exc) in enumerate(pool.map(fetch_one, list(enumerate(wanted))), 1):
                prog.step(file=j)
                if path is not None:
                    try:
                        total_bytes += path.stat().st_size
                    except OSError:
                        pass
                if exc is not None:
                    cand = _candidate(profile, r, None, meta, downloaded=False)
                    cand.url = f.url
                    out = PipelineOutcome(status="failed", candidate=cand, message=str(exc))
                    outcomes.append(out)
                    if on_outcome:
                        on_outcome(out)
                    say(f"  download failed: {f.url} — {exc}")
                    continue
                cand = _candidate(profile, r, path, meta, downloaded=True)
                cand.url = f.url
                if len(wanted) > 1 or path.name.lower() not in r.title.lower():
                    cand.title = f"{r.title} · {path.name}"
                out = ingest(cand)
                outcomes.append(out)
                if on_outcome:
                    on_outcome(out)
                _cleanup(path)
    elapsed = time.time() - started
    say(f"  collect phase: {human_bytes(total_bytes)} in {human_time(elapsed)}"
        + (f" ({human_rate(total_bytes / elapsed)})" if elapsed > 0 and total_bytes else ""))
    prog.step(stage="finished")
    return outcomes


def write_lookup_manifest(manifests_dir: Path, session_id: str, report: CatalogueRunReport) -> Path | None:
    if not report.lookups:
        return None
    manifests_dir.mkdir(parents=True, exist_ok=True)
    path = manifests_dir / f"{session_id}-lookups.json"
    path.write_text(json.dumps([
        {"catalogue": r.provider, "title": r.title, "url": r.landing_url, "query": r.query,
         "note": r.description, "recorded_at": now_iso()} for r in report.lookups
    ], indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------- helpers
def _candidate(profile: Profile, r: CatalogueResult, path: Path | None, meta: dict, downloaded: bool) -> CandidateResource:
    return CandidateResource(
        language_id=profile.id, method="catalogue", local_path=path, url=r.landing_url, title=r.title,
        source_url=r.landing_url, catalogue=r.provider, query=r.query, licence=r.licence,
        download_date=now_iso() if downloaded else None, import_method="move",
        metadata={k: v for k, v in meta.items() if isinstance(v, (str, int, float))},
        catalogue_types=list(r.types),
    )


def _write_metadata_record(temp_dir: Path, r: CatalogueResult, meta: dict) -> Path:
    temp_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^\w-]+", "_", (r.identifiers.get("glottocode") or r.identifiers.get("ia_identifier")
                                    or r.identifiers.get("handle") or r.title))[:80].strip("_")
    path = temp_dir / f"{r.provider}-{slug}.json"
    doc = {"catalogue": r.provider, "title": r.title, "landing_url": r.landing_url, "query": r.query,
           "metadata": meta, "raw": r.metadata.get("raw_json"), "identifiers": r.identifiers,
           "types": r.types, "recorded_at": now_iso()}
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def _cleanup(path: Path | None) -> None:
    """The pipeline moves the file into storage; a duplicate leaves the temp copy behind."""
    if path and path.exists():
        try:
            path.unlink()
        except OSError:
            pass
