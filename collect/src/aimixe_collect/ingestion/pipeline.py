"""The shared ingestion pipeline (specification §10).

Catalogue Search, Agent Search, Offline Scan and Manual Import all call ``run()``.

    Candidate → Relevance → Validation → Metadata → SHA-256 → Duplicate → Classification →
    Provenance → Storage → Database Index → Optional Content Extraction
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..classification.classifier import classify
from ..classification.formats import detect_format
from ..config import Config
from ..db.repositories import ResourceRepo, ReviewRepo, SessionRepo
from ..dedup.detector import DuplicateDetector
from ..discovery.candidate import CandidateResource, PipelineOutcome
from ..dedup.fuzzy import Signature, signature_for, similarity
from ..extraction.archives import extract_members
from ..extraction.basic import basic_metadata
from ..extraction.content import run_extraction
from ..logging_setup import JsonlLog, now_iso
from ..profile.model import Profile
from ..relevance.scorer import ProfileTerms, score_text, terms_from_profile
from ..storage.object_store import ObjectStore, sha256_file


# Candidate metadata that records where something was found; never counted as relevance evidence.
CONTEXT_ONLY_KEYS = {"discovered_from", "page_title", "page_score", "landing_url", "catalogue"}


@dataclass
class PipelineContext:
    config: Config
    profile: Profile
    session_id: str | None
    resources: ResourceRepo
    sessions: SessionRepo
    reviews: ReviewRepo
    store: ObjectStore
    log: JsonlLog
    terms: ProfileTerms | None = None

    def __post_init__(self) -> None:
        if self.terms is None:
            self.terms = terms_from_profile(self.profile)


class IngestionPipeline:
    def __init__(self, ctx: PipelineContext):
        self.ctx = ctx

    # ------------------------------------------------------------------ public
    def run(self, cand: CandidateResource) -> PipelineOutcome:
        ctx = self.ctx
        sid = ctx.session_id
        try:
            outcome = self._run(cand)
        except Exception as exc:  # a failed resource never stops the session
            outcome = PipelineOutcome(status="failed", candidate=cand,
                                      message=f"{type(exc).__name__}: {exc}")
        if sid:
            ctx.sessions.event(sid, "info" if outcome.status != "failed" else "error",
                               f"{outcome.status}: {cand.display}",
                               {"sha256": outcome.sha256, "relevance": outcome.relevance,
                                "message": outcome.message})
            for counter in {"stored": ["downloaded"], "duplicate_linked": ["duplicates"],
                            "uncertain_review": ["downloaded", "pending_review"], "failed": ["failed"]}.get(outcome.status, []):
                ctx.sessions.bump(sid, counter)
            if outcome.status in ("stored", "duplicate_linked", "uncertain_review"):
                ctx.sessions.bump(sid, "relevant")
        ctx.resources.commit()
        ctx.log.write("ingest", session=sid, status=outcome.status, resource=cand.display,
                      sha256=outcome.sha256, relevance=outcome.relevance, language=cand.language_id)
        return outcome

    # ----------------------------------------------------------------- stages
    def _run(self, cand: CandidateResource) -> PipelineOutcome:
        ctx = self.ctx
        path = cand.local_path
        if path is None:
            return PipelineOutcome(status="failed", candidate=cand,
                                   message="no local file (online download arrives in Phase 2)")
        path = Path(path)

        # 1. Language relevance detection ---------------------------------------------
        described = " ".join(filter(None, [
            str(path), cand.title or "", " ".join(cand.matched_terms),
            " ".join(f"{k} {v}" for k, v in cand.metadata.items()
                     if isinstance(v, str) and k not in CONTEXT_ONLY_KEYS),
        ]))
        rel = score_text(ctx.terms, described, metadata_language=cand.metadata.get("language"),
                         catalogue_types=cand.catalogue_types or None, user_asserted=cand.user_asserted,
                         discovery_confidence=cand.detection_confidence)
        if rel.score < ctx.config.review_at:
            return PipelineOutcome(status="rejected", candidate=cand, relevance=rel.score, band=rel.band,
                                   reasons=rel.reasons, message="below relevance threshold")

        # 2. Validation ------------------------------------------------------------------
        if not path.is_file():
            return PipelineOutcome(status="failed", candidate=cand, message="not a regular file")
        try:
            with path.open("rb"):
                pass
        except OSError as exc:
            return PipelineOutcome(status="failed", candidate=cand, message=f"unreadable: {exc}")
        size = path.stat().st_size
        max_bytes = int(ctx.config.get("scan", "max_file_size_mb", 4096)) * 1024 * 1024
        if size > max_bytes:
            return PipelineOutcome(status="failed", candidate=cand, message="exceeds max_file_size_mb")

        # 3. Metadata extraction ---------------------------------------------------------
        fmt = detect_format(path)
        meta = basic_metadata(path, fmt)
        meta.update({k: v for k, v in cand.metadata.items() if v is not None})
        if size == 0:
            meta["empty_file"] = "true"
        # metadata may sharpen relevance (metadata language field, embedded title)
        if meta.get("language") or meta.get("title"):
            rel2 = score_text(ctx.terms, described + " " + str(meta.get("title", "")),
                              metadata_language=str(meta.get("language")) if meta.get("language") else None,
                              catalogue_types=cand.catalogue_types or None, user_asserted=cand.user_asserted,
                              discovery_confidence=cand.detection_confidence)
            if rel2.score > rel.score:
                rel = rel2

        # 4. SHA-256 -----------------------------------------------------------------------
        sha = sha256_file(path)

        # 5. Duplicate detection -----------------------------------------------------------
        dup = DuplicateDetector(ctx.resources).check(sha, path)

        # 6. Resource classification -------------------------------------------------------
        types = classify(path, cand.title, fmt, hints=cand.catalogue_types + cand.type_hints, metadata=meta)

        status = "confirmed" if rel.score >= ctx.config.confirmed_at else "uncertain"
        mode = cand.import_method or ctx.config.storage_mode

        if dup.exact is not None:
            # 7. Provenance only: attach the new source to the existing resource, no second file
            rid = dup.exact.id
            already = ctx.resources.language_status(rid, cand.language_id)
            ctx.resources.set_language(rid, cand.language_id, rel.score, rel.band, status, rel.reasons)
            ctx.resources.add_types(rid, types)
            self._record_provenance(rid, cand)
            ctx.resources.add_metadata(rid, meta)
            # mode "move" is not applied here: never delete the user's file just because the bytes are held
            if already != "confirmed":
                self._maybe_review(cand, rid, sha, rel, status)
            return PipelineOutcome(status="duplicate_linked", candidate=cand, resource_id=rid, sha256=sha,
                                   relevance=rel.score, band=rel.band, reasons=rel.reasons,
                                   types=[t for t, _, _ in types],
                                   message=f"duplicate of resource #{rid} ({dup.exact.original_name})")

        # 8. Storage -------------------------------------------------------------------------
        dest_dir = ctx.config.paths.resources_dir(cand.language_id, fmt.category)
        stored = ctx.store.store(path, dest_dir, sha, mode=mode)

        # 9. Database index --------------------------------------------------------------------
        row = ctx.resources.insert(sha, size, path.name, fmt.format, fmt.mime, fmt.category,
                                   str(stored.path), stored.mode)
        ctx.resources.set_language(row.id, cand.language_id, rel.score, rel.band, status, rel.reasons)
        ctx.resources.add_types(row.id, types)
        self._record_provenance(row.id, cand)
        ctx.resources.add_metadata(row.id, meta)
        self._write_sidecar(cand.language_id, row.id, sha, path, stored.path, fmt, meta, rel, types, cand)

        # 10. Optional content extraction ------------------------------------------------------
        text = ""
        if ctx.config.get("extraction", "enabled", True):
            out_dir = ctx.config.paths.extracted_dir(cand.language_id) / f"{row.id}-{sha[:12]}"
            outputs, text, extra = run_extraction(
                stored.path, fmt, out_dir, meta, int(ctx.config.get("extraction", "max_text_mb", 50)) * 1024 * 1024)
            for kind, epath in outputs:
                ctx.resources.add_extraction(row.id, kind, str(epath))
            if extra:
                ctx.resources.add_metadata(row.id, {k: v for k, v in extra.items() if k != "archive_listing"}, "content")
            if text and not cand.synthetic:
                # document contents are a relevance signal (§7) and may refine classification (§14)
                rel3 = score_text(ctx.terms, described, metadata_language=str(meta.get("language")) if meta.get("language") else None,
                                  catalogue_types=cand.catalogue_types or None, user_asserted=cand.user_asserted,
                                  discovery_confidence=cand.detection_confidence, contents=text)
                if rel3.score > rel.score:
                    rel = rel3
                    status = "confirmed" if rel.score >= ctx.config.confirmed_at else "uncertain"
                    ctx.resources.set_language(row.id, cand.language_id, rel.score, rel.band, status, rel.reasons)
                more = classify(path, cand.title, fmt, hints=cand.catalogue_types + cand.type_hints,
                                metadata={**meta, "description": text[:4000]})
                ctx.resources.add_types(row.id, [(t, c, "content") for t, c, _ in more if t != "unknown"])
                types = sorted({*types, *[(t, c, "content") for t, c, _ in more if t != "unknown"]}, key=lambda x: -x[1])

        # 11. Fuzzy duplicate detection (§13) ---------------------------------------------------
        near = self._fuzzy(row.id, cand.language_id, fmt.category, text)

        # 12. Archive members (Phase 4) ----------------------------------------------------------
        member_outcomes = []
        if fmt.category == "archives" and ctx.config.get("archives", "ingest_members", False):
            member_outcomes = self._ingest_members(cand, stored.path, fmt.format, row.id)

        self._maybe_review(cand, row.id, sha, rel, status)
        final = "uncertain_review" if status == "uncertain" else "stored"
        msg = str(stored.path)
        if near:
            msg += f" (near-duplicate of #{near[0][0]} at {near[0][1]:.0%})"
        if member_outcomes:
            msg += f"; {len(member_outcomes)} archive member(s) ingested"
        return PipelineOutcome(status=final, candidate=cand, resource_id=row.id, sha256=sha,
                               relevance=rel.score, band=rel.band, reasons=rel.reasons,
                               types=[t for t, _, _ in types], message=msg)

    # ---------------------------------------------------------------- phase-4 stages
    def _fuzzy(self, rid: int, language_id: str, category: str, text: str) -> list[tuple[int, float]]:
        ctx = self.ctx
        if not ctx.config.get("dedup", "fuzzy", True):
            return []
        sig, note = signature_for(category, text or None)
        if sig is None:
            if note and category in ("images", "audio", "video"):
                ctx.resources.add_metadata(rid, {"fuzzy_dedup": note}, "content")
            return []
        ctx.resources.set_signature(rid, sig.kind, sig.values, sig.tokens)
        threshold = float(ctx.config.get("dedup", "threshold", 0.85))
        found: list[tuple[int, float]] = []
        for other_id, values, tokens in ctx.resources.signatures_for_language(language_id, sig.kind, exclude=rid):
            s = similarity(sig, Signature(sig.kind, values, tokens))
            if s >= threshold:
                ctx.resources.add_near_duplicate(rid, other_id, s, "text-minhash")
                found.append((other_id, s))
        found.sort(key=lambda x: -x[1])
        return found

    def _ingest_members(self, cand: CandidateResource, archive: Path, fmt: str, archive_rid: int) -> list[PipelineOutcome]:
        ctx = self.ctx
        temp = ctx.config.paths.temp / f"archive-{archive_rid}"
        outs: list[PipelineOutcome] = []
        try:
            members = extract_members(archive, fmt, temp, max_members=int(ctx.config.get("archives", "max_members", 200)))
        except Exception as exc:
            ctx.log.write("archive.failed", resource=archive_rid, error=str(exc))
            return outs
        for mpath, mname in members:
            mc = CandidateResource(
                language_id=cand.language_id, method=cand.method, local_path=mpath, title=mname,
                source_url=cand.source_url, catalogue=cand.catalogue, url=cand.url, query=cand.query,
                licence=cand.licence, original_path=f"{cand.original_path or archive}!{mname}",
                detection_method="archive_member", detection_confidence=cand.detection_confidence,
                import_method="move", user_asserted=cand.user_asserted, matched_terms=list(cand.matched_terms),
                metadata={"archive_resource_id": archive_rid, "archive_member": mname})
            outs.append(self.run(mc))
        try:
            import shutil
            shutil.rmtree(temp, ignore_errors=True)
        except OSError:
            pass
        return outs

    # ---------------------------------------------------------------- helpers
    def _record_provenance(self, rid: int, cand: CandidateResource) -> None:
        self.ctx.resources.add_source(
            rid, cand.language_id, self.ctx.session_id, cand.method,
            source_url=cand.source_url, catalogue=cand.catalogue, resource_url=cand.url, query=cand.query,
            discovery_date=cand.discovery_date, download_date=cand.download_date, licence=cand.licence,
            original_path=cand.original_path or (str(cand.local_path) if cand.local_path and cand.method in ("offline", "import") else None),
            detection_method=cand.detection_method, confidence=cand.detection_confidence,
            import_method=cand.import_method,
        )

    def _maybe_review(self, cand, rid, sha, rel, status) -> None:
        if status != "uncertain":
            return
        self.ctx.reviews.add(cand.language_id, self.ctx.session_id, "resource",
                             {"resource_id": rid, "sha256": sha, "name": cand.display,
                              "relevance": rel.score, "band": rel.band, "reasons": rel.reasons,
                              "path": str(cand.local_path) if cand.local_path else cand.url,
                              "source_url": cand.source_url, "url": cand.url},
                             rel.score / 100.0,
                             (cand.original_path or str(cand.local_path)) if cand.method in ("offline", "import")
                             else (cand.url or cand.source_url or str(cand.local_path)))

    def _write_sidecar(self, language_id, rid, sha, original, stored, fmt, meta, rel, types, cand) -> None:
        mdir = self.ctx.config.paths.metadata_dir(language_id)
        mdir.mkdir(parents=True, exist_ok=True)
        doc = {
            "resource_id": rid, "sha256": sha, "original_name": original.name, "stored_path": str(stored),
            "format": fmt.format, "category": fmt.category, "mime": fmt.mime,
            "resource_types": [{"type": t, "confidence": c, "source": s} for t, c, s in types],
            "relevance": {"score": rel.score, "band": rel.band, "reasons": rel.reasons},
            "discovery": {"method": cand.method, "source_url": cand.source_url, "catalogue": cand.catalogue,
                          "query": cand.query, "discovery_date": cand.discovery_date,
                          "original_path": cand.original_path or str(original),
                          "detection_method": cand.detection_method, "confidence": cand.detection_confidence,
                          "import_method": cand.import_method, "session_id": self.ctx.session_id},
            "metadata": meta, "recorded_at": now_iso(),
        }
        (mdir / f"{rid}-{sha[:12]}.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False, default=str),
                                                     encoding="utf-8")
