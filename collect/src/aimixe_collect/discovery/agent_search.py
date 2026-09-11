"""Agent Search orchestration (specification §6): the fifteen steps, bounded and explainable.

 1 understand the profile → SearchContext      9 estimate relevance (agent.analyze + scorer)
 2 generate queries (rule + agent)             10 detect duplicates (URL normalisation, SHA-256 in pipeline)
 3 search the web (backends)                   11 download allowed resources (robots, size cap)
 4 follow relevant pages (depth/host bounded)  12 store the source URL
 5 discover downloadable resources             13 store discovery metadata (query, page chain)
 6 discover datasets/archives (repo patterns)  14 classify (pipeline + agent.classify hints)
 7 identify metadata (title, meta tags)        15 learn: new names/varieties → new queries + review proposals
 8 decide whether it relates to the language
"""
from __future__ import annotations

import re
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..agent.base import AgentProvider, AgentQuery, AnalysisContext, Evidence, ProposedFact
from ..agent.rule_based import extract_facts
from ..catalogues import http
from ..language.registry import fold
from ..logging_setup import now_iso
from ..profile.model import Profile
from ..progress import Progress
from ..relevance.scorer import terms_from_profile
from .candidate import CandidateResource, PipelineOutcome
from .web import (Page, WebHit, WebSearchBackend, allowed_by_robots, fetch_page, looks_like_file,
                  normalise_url, skip_host)

REPO_PATTERNS = [
    (re.compile(r"https?://zenodo\.org/records?/(\d+)"), "zenodo"),
    (re.compile(r"https?://archive\.org/details/([^/?#]+)"), "internet_archive"),
    (re.compile(r"https?://github\.com/([^/]+/[^/]+)/blob/(.+)"), "github_blob"),
]


@dataclass
class SearchLimits:
    max_queries: int = 16
    hits_per_query: int = 8
    max_pages: int = 40
    max_depth: int = 2
    per_host: int = 6
    max_rounds: int = 2
    max_files: int = 40
    max_bytes: int = 200 * 1024 * 1024
    timeout: int = 30


@dataclass
class SessionKnowledge:
    """What this session learned; it improves later queries without touching the profile."""
    new_terms: dict[str, str] = field(default_factory=dict)      # term -> kind (variety | alternate_name | place)
    proposals: list[ProposedFact] = field(default_factory=list)

    sink: object = None          # a ProfileTerms the pipeline scores with; learned names are appended there

    max_terms: int = 12          # a session learns at most this many new names
    per_page: int = 5            # … and at most this many from one page

    def learn(self, facts: list[ProposedFact], known: set[str], is_other_language=None) -> list[str]:
        added = []
        for f in facts:
            values = f.value if isinstance(f.value, list) else [f.value]
            for v in values:
                name = v.get("name") if isinstance(v, dict) else v
                if not isinstance(name, str):
                    continue
                name = _clean_name(name)
                k = fold(name)
                if not k or len(added) >= self.per_page or len(self.new_terms) >= self.max_terms:
                    continue
                if is_other_language and is_other_language(name):
                    continue                         # "Thai", "Lao", "Shan": languages of their own, not our varieties
                if k and k not in known and k not in self.new_terms and f.field in ("varieties", "alternate_names", "exonyms"):
                    self.new_terms[name] = f.field
                    added.append(name)
                    if self.sink is not None:
                        target = {"varieties": "varieties", "alternate_names": "alternate_names",
                                  "exonyms": "exonyms", "places": "places"}[f.field]
                        getattr(self.sink, target).append(name)
        self.proposals.extend(facts)
        return added


@dataclass
class AgentSearchReport:
    queries: list[AgentQuery] = field(default_factory=list)
    hits: int = 0
    pages_fetched: int = 0
    pages_relevant: int = 0
    files_found: int = 0
    learned: list[str] = field(default_factory=list)
    proposals: list[ProposedFact] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    visited: list[dict] = field(default_factory=list)          # url, score, action


class AgentSearchRunner:
    def __init__(self, agent: AgentProvider, backends: list[WebSearchBackend], profile: Profile,
                 *, review_at: int, confirmed_at: int, limits: SearchLimits | None = None,
                 progress: Progress | None = None, learn_only: bool = False):
        self.progress = progress or Progress()
        self.learn_only = learn_only          # profile enrichment: propose facts, download nothing
        self.agent = agent
        self.agent.bind(profile)
        self.backends = backends
        self.profile = profile
        self.review_at = review_at
        self.confirmed_at = confirmed_at
        self.limits = limits or SearchLimits()
        self.terms = terms_from_profile(profile)
        self.knowledge = SessionKnowledge(sink=self.terms)
        self.known_terms: set[str] = {fold(x) for x in [profile.name, *self.terms.alternate_names, *self.terms.exonyms,
                                                        *self.terms.varieties, *self.terms.places] if x}
        self._downloaded = 0
        try:
            from ..language.registry import load_registry
            self._registry = load_registry()
        except Exception:
            self._registry = None
        self.report = AgentSearchReport()
        self._seen_urls: set[str] = set()
        self._host_counts: dict[str, int] = {}
        self._file_urls: set[str] = set()

    # ------------------------------------------------------------ plan
    def plan(self) -> list[AgentQuery]:
        qs = self.agent.generate_search_queries(self.profile)[: self.limits.max_queries]
        self.report.queries = qs
        return qs

    def learned_queries(self) -> list[AgentQuery]:
        out = []
        for term, kind in self.knowledge.new_terms.items():
            if any(fold(q.text) == fold(f'"{term}" dictionary') for q in self.report.queries):
                continue
            if kind == "varieties":
                for tmpl in (f'"{term}" dictionary', f'"{term}" language documentation', f'"{term}" "{self.profile.name}" corpus'):
                    out.append(AgentQuery(tmpl, "learned", f"{term} discovered as a variety during this session"))
            elif kind in ("alternate_names", "exonyms"):
                out.append(AgentQuery(f'"{term}" language', "learned", f"{term} discovered as another name"))
            elif kind == "places":
                out.append(AgentQuery(f'"{self.profile.name}" "{term}"', "learned", f"{term} discovered as a place"))
        return out

    # ------------------------------------------------------------ run
    def run(self, queries: list[AgentQuery], temp_dir: Path, ingest: Callable[[CandidateResource], PipelineOutcome],
            *, on_message: Callable[[str], None] | None = None,
            on_outcome: Callable[[PipelineOutcome], None] | None = None) -> list[PipelineOutcome]:
        say = on_message or (lambda m: None)
        outcomes: list[PipelineOutcome] = []
        pending = list(queries)
        rounds = 0
        while pending and rounds < self.limits.max_rounds:
            rounds += 1
            batch, pending = pending, []
            for q in batch:
                if self.report.pages_fetched >= self.limits.max_pages:
                    break
                hits = self._search(q)
                self.progress.step(stage="searching", query=q.text, round=rounds, pages=self.report.pages_fetched,
                                   max_pages=self.limits.max_pages, files=len(self._file_urls))
                say(f"  {q.text}  →  {len(hits)} hit(s)")
                for hit in hits:
                    if self.report.pages_fetched >= self.limits.max_pages or \
                            (self.limits.max_files and self._downloaded >= self.limits.max_files):
                        break
                    try:
                        outcomes.extend(self._visit(hit.url, q.text, depth=1, temp_dir=temp_dir, ingest=ingest,
                                                    title=hit.title, snippet=hit.snippet, say=say, on_outcome=on_outcome))
                    except KeyboardInterrupt:
                        raise
                    except Exception as exc:  # one bad page must not end the run
                        msg = f"{hit.url[:80]}: {type(exc).__name__}: {exc}"
                        self.report.errors.append(msg)
                        say(f"    ! {msg[:140]}")
            # step 15: what was learned becomes the next round's queries
            new_q = self.learned_queries()
            already = {fold(x.text) for x in self.report.queries}
            new_q = [x for x in new_q if fold(x.text) not in already][: self.limits.max_queries]
            if new_q:
                say(f"  learned {len(self.knowledge.new_terms)} new term(s): " + ", ".join(list(self.knowledge.new_terms)[:6]))
                self.report.queries.extend(new_q)
                pending.extend(new_q)
        self.report.proposals = self.knowledge.proposals
        self.report.learned = list(self.knowledge.new_terms)
        return outcomes

    def _is_other_language(self, name: str) -> bool:
        """True when ``name`` is the reference name of another ISO language (so not a variety of ours)."""
        if self._registry is None:
            return False
        for c in self._registry.find(name, limit=3):
            if c.matched_on == "name" and c.score >= 0.98 and c.record.code != self.profile.iso639_3:
                return True
        return False

    def _search(self, q: AgentQuery) -> list[WebHit]:
        hits: list[WebHit] = []
        seen: set[str] = set()
        for b in self.backends:
            try:
                for h in b.search(q.text, limit=self.limits.hits_per_query):
                    n = normalise_url(h.url)
                    if n in seen or skip_host(h.url):
                        continue
                    seen.add(n)
                    hits.append(h)
            except http.HttpError as exc:
                msg = f"{b.name}: {exc}"
                if msg not in self.report.errors:
                    self.report.errors.append(msg)
            except Exception as exc:  # a backend must never stop the run
                self.report.errors.append(f"{b.name}: {type(exc).__name__}: {exc}")
        self.report.hits += len(hits)
        return hits

    # ------------------------------------------------------------ visiting
    def _visit(self, url: str, query: str, depth: int, temp_dir: Path, ingest, *, title: str = "", snippet: str = "",
               say, on_outcome, parent: str | None = None) -> list[PipelineOutcome]:
        outcomes: list[PipelineOutcome] = []
        n = normalise_url(url)
        if n in self._seen_urls or depth > self.limits.max_depth:
            return outcomes
        self._seen_urls.add(n)
        host = urllib.parse.urlparse(url).netloc.lower()
        if self._host_counts.get(host, 0) >= self.limits.per_host:
            return outcomes
        if not allowed_by_robots(url):
            self.report.visited.append({"url": url, "action": "robots-disallowed"})
            return outcomes
        if looks_like_file(url) or _repo_kind(url):
            if not self.learn_only:
                outcomes.extend(self._file(url, query, parent or url, title, temp_dir, ingest, say, on_outcome))
            return outcomes
        self._host_counts[host] = self._host_counts.get(host, 0) + 1
        try:
            page = fetch_page(url, timeout=self.limits.timeout)
        except http.HttpError as exc:
            self.report.errors.append(f"fetch {url}: {exc}")
            self.report.visited.append({"url": url, "action": "fetch-failed"})
            return outcomes
        self.report.pages_fetched += 1
        self.progress.step(stage="reading pages", pages=self.report.pages_fetched, max_pages=self.limits.max_pages,
                           files=len(self._file_urls), url=url[:80])
        if page.is_file:
            if not self.learn_only:
                outcomes.extend(self._file(url, query, parent or url, title, temp_dir, ingest, say, on_outcome))
            return outcomes
        analysis = self.agent.analyze(AnalysisContext(self.profile, url, page.title or title, page.text[:20000], snippet,
                                                      {"language": page.meta.get("dc.language") or page.meta.get("language")},
                                                      terms=self.terms))
        action = "skip"
        if analysis.score >= self.review_at:
            self.report.pages_relevant += 1
            action = "relevant"
            # step 15: learn from the page — only when the page is clearly about this language, and never
            # names that the ISO/Glottolog tables list as languages in their own right
            if analysis.score >= self.confirmed_at and _page_is_about_us(page, self.profile, self.terms):
                facts = self.agent.enrich_language_profile(Evidence(page.text[:60000], url, page.title))
                facts = [f for f in _filter_facts(facts, self.profile, self.known_terms)]
                added = self.knowledge.learn(facts, self.known_terms, is_other_language=self._is_other_language)
                if added:
                    say(f"    learned: {', '.join(added[:5])}  ({url})")
            else:
                say(f"    (page mentions the language but is not about it; nothing learned from {url[:70]})")
            # step 5/6: files linked from the page
            for link, anchor in ([] if self.learn_only else page.links):
                if self.limits.max_files and self._downloaded >= self.limits.max_files:
                    break
                if skip_host(link) or normalise_url(link) in self._seen_urls:
                    continue
                if looks_like_file(link) or _repo_kind(link):
                    outcomes.extend(self._file(link, query, url, anchor or page.title, temp_dir, ingest, say, on_outcome,
                                               page_score=analysis.score, page_title=page.title))
            # a relevant HTML page is itself a resource (online dictionaries, documentation sites)
            if analysis.score >= self.confirmed_at and not self.learn_only:
                outcomes.extend(self._store_page(page, query, temp_dir, ingest, on_outcome, analysis.score,
                                                 analysis.resource_types))
            # step 4: follow links whose anchor text mentions the language or its varieties
            if depth < self.limits.max_depth:
                for link, anchor in _relevant_links(page.links, self.terms, self.knowledge, limit=6):
                    try:
                        outcomes.extend(self._visit(link, query, depth + 1, temp_dir, ingest, title=anchor, say=say,
                                                    on_outcome=on_outcome, parent=url))
                    except KeyboardInterrupt:
                        raise
                    except Exception as exc:
                        self.report.errors.append(f"{link[:80]}: {type(exc).__name__}: {exc}")
        self.report.visited.append({"url": url, "score": analysis.score, "action": action, "title": page.title[:120],
                                    "reasons": analysis.reasons[:4]})
        return outcomes

    def _file(self, url: str, query: str, source_url: str, title: str, temp_dir: Path, ingest, say, on_outcome,
              page_score: int | None = None, page_title: str | None = None) -> list[PipelineOutcome]:
        n = normalise_url(url)
        if n in self._file_urls:
            return []
        self._file_urls.add(n)
        self._seen_urls.add(n)
        self.report.files_found += 1
        kind = _repo_kind(url)
        if kind == "zenodo" or kind == "internet_archive":
            # datasets/archives: let the catalogue layer's knowledge of the repository fetch the file list
            return self._repo_record(url, kind, query, title, temp_dir, ingest, on_outcome, say)
        if kind == "github_blob":
            url = re.sub(r"github\.com/([^/]+/[^/]+)/blob/", r"raw.githubusercontent.com/\1/", url)
        pre = self.agent.analyze(AnalysisContext(self.profile, url, title, "", None, terms=self.terms))
        score = max(pre.score, (page_score or 0) - 20)
        if score < self.review_at:
            self.report.visited.append({"url": url, "score": score, "action": "file-skipped"})
            return []
        if not allowed_by_robots(url):
            self.report.visited.append({"url": url, "action": "robots-disallowed"})
            return []
        fname = urllib.parse.unquote(url.rsplit("/", 1)[-1])[:60] or url[:60]
        key = f"file:{len(self._file_urls)}"
        self.progress.start(key, fname, None)
        try:
            path = http.download_file(url, temp_dir, max_bytes=self.limits.max_bytes, timeout=self.limits.timeout,
                                      progress=self.progress.callback(key))
            self.progress.done(key, ok=True)
        except http.HttpError as exc:
            self.progress.done(key, ok=False, message=str(exc))
            cand = CandidateResource(language_id=self.profile.id, method="agent", url=url, source_url=source_url,
                                     query=query, title=title)
            out = PipelineOutcome(status="failed", candidate=cand, message=str(exc))
            self.report.errors.append(f"download {url}: {exc}")
            if on_outcome:
                on_outcome(out)
            return [out]
        self._downloaded += 1
        cand = CandidateResource(language_id=self.profile.id, method="agent", local_path=path, url=url,
                                 source_url=source_url, query=query, title=title or path.name,
                                 download_date=now_iso(), import_method="move",
                                 metadata={"discovered_from": source_url, "page_score": page_score,
                                           "page_title": page_title},
                                 matched_terms=pre.language_hints, type_hints=pre.resource_types)
        out = ingest(cand)
        _cleanup(path)
        if on_outcome:
            on_outcome(out)
        self.report.visited.append({"url": url, "score": out.relevance, "action": out.status})
        return [out]

    def _repo_record(self, url: str, kind: str, query: str, title: str, temp_dir: Path, ingest, on_outcome, say):
        from ..catalogues.base import DownloadableFile
        from ..catalogues.builtin.internet_archive import InternetArchiveProvider
        from ..catalogues.configurable import path_get
        files: list[DownloadableFile] = []
        licence = None
        try:
            if kind == "zenodo":
                rid = re.search(r"/records?/(\d+)", url).group(1)
                data = http.get_json(f"https://zenodo.org/api/records/{rid}")
                title = title or path_get(data, "metadata.title") or title
                licence = path_get(data, "metadata.license.id")
                for u in (path_get(data, "files[].links.self") or [])[: self.limits.max_files]:
                    files.append(DownloadableFile(url=u))
            else:
                ident = re.search(r"archive\.org/details/([^/?#]+)", url).group(1)
                from ..catalogues.base import CatalogueResult
                r = CatalogueResult(provider="internet_archive", kind="record", title=title or ident, landing_url=url,
                                    identifiers={"ia_identifier": ident})
                InternetArchiveProvider({"max_files_per_record": 10}).fetch(r)
                files = r.files
        except (http.HttpError, AttributeError) as exc:
            self.report.errors.append(f"{kind} {url}: {exc}")
            return []
        say(f"    {kind} record: {title[:60]} — {len(files)} file(s)")
        outs = []
        for f in files[:10]:
            try:
                path = http.download_file(f.url, temp_dir, filename=f.filename, max_bytes=self.limits.max_bytes)
            except http.HttpError as exc:
                self.report.errors.append(f"download {f.url}: {exc}")
                continue
            cand = CandidateResource(language_id=self.profile.id, method="agent", local_path=path, url=f.url,
                                     source_url=url, catalogue=kind, query=query, title=title, licence=licence,
                                     download_date=now_iso(), import_method="move")
            out = ingest(cand)
            _cleanup(path)
            outs.append(out)
            if on_outcome:
                on_outcome(out)
        return outs

    def _store_page(self, page: Page, query: str, temp_dir: Path, ingest, on_outcome, score: int, types: list[str]):
        temp_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^\w-]+", "_", (page.title or urllib.parse.urlparse(page.url).path))[:80].strip("_") or "page"
        path = temp_dir / f"{slug}.html"
        try:
            body, _ = http.get_bytes(page.url, accept="text/html", use_cache=True)
            path.write_bytes(body)
        except http.HttpError:
            return []
        cand = CandidateResource(language_id=self.profile.id, method="agent", local_path=path, url=page.url,
                                 source_url=page.url, query=query, title=page.title, download_date=now_iso(),
                                 import_method="move", metadata={"page_score": score, **{k: v for k, v in page.meta.items()
                                                                                          if k in ("description", "dc.title", "dc.language", "og:title")}},
                                 type_hints=types)
        out = ingest(cand)
        _cleanup(path)
        if on_outcome:
            on_outcome(out)
        return [out]


# ---------------------------------------------------------------- helpers
def _clean_name(name: str) -> str:
    """Strip footnote marks and bracketed glosses: "Zhuang–Tai[1]" → "Zhuang–Tai", "Lao (Laotian)" → "Lao"."""
    name = re.sub(r"\[\d+\]", "", name)
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name)
    return name.strip(" .,;:")


def _repo_kind(url: str) -> str | None:
    for pat, kind in REPO_PATTERNS:
        if pat.search(url):
            return kind
    return None


def _relevant_links(links: list[tuple[str, str]], terms, knowledge: SessionKnowledge, limit: int) -> list[tuple[str, str]]:
    names = [terms.name, *terms.alternate_names[:6], *terms.varieties[:10], *knowledge.new_terms]
    out = []
    for link, anchor in links:
        if skip_host(link):
            continue
        blob = fold(anchor + " " + link)
        if any(fold(n) and f" {fold(n)} " in f" {blob} " for n in names if n):
            out.append((link, anchor))
            if len(out) >= limit:
                break
    return out


def _page_is_about_us(page: Page, profile: Profile, terms) -> bool:
    """The page title or its first lines name this language (a family overview page does not qualify)."""
    head = fold((page.title or "") + " " + page.text[:600])
    names = [profile.name, *terms.alternate_names[:6]]
    return any(fold(n) and f" {fold(n)} " in f" {head} " for n in names if n)


def _filter_facts(facts: list[ProposedFact], profile: Profile, known: set[str]):
    for f in facts:
        vals = f.value if isinstance(f.value, list) else [f.value]
        keep = []
        for v in vals:
            name = v.get("name") if isinstance(v, dict) else v
            if isinstance(name, str) and fold(name) in known:
                continue
            keep.append(v)
        if not keep:
            continue
        if f.field == "family" and profile.is_known("identity", "family"):
            cur = fold(str(profile.display_value("identity", "family")))
            if fold(str(f.value)) in cur or cur in fold(str(f.value)):
                continue
        f.value = keep if isinstance(f.value, list) else keep[0]
        yield f


def _cleanup(path: Path | None) -> None:
    if path and path.exists():
        try:
            path.unlink()
        except OSError:
            pass
