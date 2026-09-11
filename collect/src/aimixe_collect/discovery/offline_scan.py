"""Offline Collection: scan local storage for language-related material (specification §8).

Terms come from the whole profile: name, ISO code, alternative names, exonyms, varieties,
community names, places, known titles/authors/organisations. A local file may carry a
dialect name rather than the ISO language name, so every term is searched.
"""
from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from ..language.registry import fold
from ..profile.model import Profile
from ..relevance.scorer import terms_from_profile
from .candidate import CandidateResource


@dataclass
class ScanTerm:
    text: str
    kind: str        # name | iso_code | alternate_name | exonym | variety | community | place | title | author | organisation
    weight: float    # detection confidence when matched alone


@dataclass
class ScanReport:
    roots: list[Path]
    files_seen: int = 0
    dirs_skipped: int = 0
    hits: int = 0
    terms: list[ScanTerm] = field(default_factory=list)


def scan_terms(profile: Profile) -> list[ScanTerm]:
    t = terms_from_profile(profile)
    out: list[ScanTerm] = [ScanTerm(t.name, "name", 0.9)]
    if t.iso:
        out.append(ScanTerm(t.iso, "iso_code", 0.85))
    out += [ScanTerm(x, "alternate_name", 0.8) for x in t.alternate_names]
    out += [ScanTerm(x, "exonym", 0.75) for x in t.exonyms]
    out += [ScanTerm(x, "variety", 0.75) for x in t.varieties]
    out += [ScanTerm(x, "community", 0.6) for x in t.community]
    out += [ScanTerm(x, "place", 0.45) for x in t.places]
    for entry in profile.collected("translation_publication", "publication") + \
            profile.collected("translation_publication", "translation"):
        if isinstance(entry, dict):
            if entry.get("title"):
                out.append(ScanTerm(str(entry["title"]), "title", 0.7))
            if entry.get("author"):
                out.append(ScanTerm(str(entry["author"]), "author", 0.5))
            if entry.get("organisation") or entry.get("organization"):
                out.append(ScanTerm(str(entry.get("organisation") or entry.get("organization")), "organisation", 0.4))
    # de-duplicate, drop very short terms that would match everything
    seen: set[str] = set()
    result: list[ScanTerm] = []
    for term in out:
        k = fold(term.text)
        if len(k) < 3 or k in seen:
            continue
        seen.add(k)
        result.append(term)
    return result


def _match(text: str, term: ScanTerm) -> bool:
    ft = fold(term.text)
    blob = f" {fold(text)} "
    if term.kind == "iso_code":
        return f" {ft} " in blob
    return f" {ft} " in blob or (len(ft) >= 8 and ft in blob)


def scan(profile: Profile, roots: list[Path], exclude_dirs: list[str],
         progress: Callable[[int, Path, int], None] | None = None, *, content: bool = False,
         content_max_bytes: int = 20 * 1024 * 1024) -> Iterator[tuple[CandidateResource, ScanReport]]:
    """Yield a candidate per matching file. The final ``ScanReport`` is on every yield.

    With ``content=True`` files whose names do not match are also read (text-bearing formats,
    bounded size) and matched on their contents: a wordlist named ``list3.txt`` whose first
    lines say "Mossang" is found that way.
    """
    terms = scan_terms(profile)
    report = ScanReport(roots=roots, terms=terms)
    excl = {e.lower() for e in exclude_dirs}
    for root in roots:
        root = root.expanduser()
        if root.is_file():
            cand = _candidate_for(profile.id, root, root.parent, terms) or \
                (_content_candidate(profile.id, root, terms, content_max_bytes) if content else None)
            report.files_seen += 1
            if cand:
                report.hits += 1
                yield cand, report
            continue
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            keep = []
            for d in dirnames:
                if d.lower() in excl or d.startswith("."):
                    report.dirs_skipped += 1
                else:
                    keep.append(d)
            dirnames[:] = keep
            dp = Path(dirpath)
            for fn in filenames:
                report.files_seen += 1
                p = dp / fn
                if progress and report.files_seen % 200 == 0:
                    progress(report.files_seen, p, report.hits)
                cand = _candidate_for(profile.id, p, root, terms)
                if cand is None and content:
                    cand = _content_candidate(profile.id, p, terms, content_max_bytes)
                if cand:
                    report.hits += 1
                    yield cand, report
    # make the report reachable even when nothing matched
    yield None, report  # type: ignore[misc]


_CONTENT_CATEGORIES = ("text", "documents")


def _content_candidate(language_id: str, path: Path, terms: list[ScanTerm], max_bytes: int) -> CandidateResource | None:
    """Look inside a file whose name said nothing (Phase 4 content-aware scanning)."""
    from ..classification.formats import detect_format
    from ..extraction.text import extract_text
    try:
        if not path.is_file() or path.stat().st_size > max_bytes or path.stat().st_size == 0:
            return None
    except OSError:
        return None
    fmt = detect_format(path)
    if fmt.category not in _CONTENT_CATEGORIES:
        return None
    text, info, _ = extract_text(path, fmt, max_bytes=max_bytes)
    if not text:
        return None
    sample = text[:400_000]
    hits = [t for t in terms if t.kind != "iso_code" and _match(sample, t)]
    strong = [t for t in hits if t.kind in ("name", "alternate_name", "exonym", "variety", "title")]
    if not strong:
        return None
    conf = max(t.weight for t in strong) * 0.75
    return CandidateResource(
        language_id=language_id, method="offline", local_path=path, original_path=str(path),
        detection_method="content", detection_confidence=round(min(conf, 0.9), 2),
        matched_terms=[t.text for t in hits], metadata={"content_extractor": info.get("extractor")})


def _candidate_for(language_id: str, path: Path, root: Path, terms: list[ScanTerm]) -> CandidateResource | None:
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    name_hits = [t for t in terms if _match(path.name, t)]
    path_hits = [t for t in terms if t not in name_hits and _match(str(rel.parent), t)]
    if not name_hits and not path_hits:
        return None
    conf = 0.0
    for t in name_hits:
        conf = max(conf, t.weight)
    for t in path_hits:
        conf = max(conf, t.weight * 0.8)
    method = "filename" if name_hits else "path"
    if name_hits and path_hits:
        method = "filename+path"
        conf = min(1.0, conf + 0.05)
    return CandidateResource(
        language_id=language_id, method="offline", local_path=path,
        original_path=str(path), detection_method=method, detection_confidence=round(conf, 2),
        matched_terms=[t.text for t in name_hits + path_hits],
    )
