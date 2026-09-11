"""The interactive ``aimixe collect`` workflow (specification §1–§4, §8, §9, §17)."""
from __future__ import annotations

from pathlib import Path

from ..discovery.candidate import PipelineOutcome
from ..language.resolver import ResolvedLanguage, Resolution
from ..profile.model import Profile
from ..progress import Progress
from ..services.app import App
from ..services.collection_service import SessionSummary
from ..storage.object_store import STORAGE_MODES
from . import render as r
from .profile_wizard import ProfileWizard
from .render import Abort
from .review_ui import run_review


# ------------------------------------------------------------------ §1 language step
def show_detected(m: ResolvedLanguage) -> None:
    r.heading("Language detected")
    r.out(f"Name: {m.name}")
    r.out(f"ISO 639-3: {m.iso639_3 or '— (local identifier ' + m.language_id + ')'}")
    if m.alternative_names:
        r.out(f"Alternative names: {', '.join(m.alternative_names[:6])}")
    if m.region:
        r.out(f"Region: {m.region}")
    if m.record and m.record.family:
        r.out(f"Family: {m.record.family}")
    if m.matched_on not in ("name", "code"):
        r.out(f"Matched on: {m.matched_on.replace('_', ' ')} “{m.matched_text}”")
    if m.source == "local_registry":
        r.out("Source: local language registry (profile already stored)")
    r.out()


def pick_language(app: App, preset: str | None = None, assume_yes: bool = False) -> Profile | None:
    """Ask for a language name or ISO code and return a saved profile, or None to quit."""
    query = preset
    while True:
        if not query:
            query = r.prompt("Enter language name or ISO 639-3 code:")
            if not query:
                continue
        res: Resolution = app.language_service.resolve(query)
        chosen: ResolvedLanguage | None = None
        if res.status == "exact":
            chosen = res.best
            show_detected(chosen)
            if not assume_yes and not r.ask_yes_no("Continue with this language?"):
                chosen = None
                if res.matches[1:] and r.ask_yes_no("Choose from other candidates?", default=False):
                    chosen = _choose_candidate(app, res.matches[1:])
        elif res.status == "ambiguous":
            if assume_yes and res.best and res.best.score >= 0.9:
                chosen = res.best
            else:
                r.out(f"\nSeveral languages match “{query}”.")
                chosen = _choose_candidate(app, res.matches)
        else:
            r.out(f"\nNo language found for “{query}” in the local registry or the bundled ISO 639-3 / Glottolog tables.")

        if chosen is not None:
            profile, created = app.language_service.open_from_resolution(chosen)
            if created:
                r.out(f"Profile created for {profile.name} [{profile.iso639_3 or profile.id}].")
            return profile

        # not identified: language-identification step
        idx = r.choose("Language identification", [
            "Search again with a different name or code",
            "Create a new language profile with this name",
            "Exit",
        ])
        if idx == 0:
            query = None
            continue
        if idx == 1:
            name = r.prompt("Language name to record:", default=query) or query
            code = r.prompt("ISO 639-3 code, if you know one (blank for a local identifier):")
            if code and not app.registry.by_code(code):
                r.out(f"“{code}” is not in the ISO 639-3 table; a local identifier will be used instead.")
                code = ""
            profile = app.language_service.create_local(name, code or None)
            r.out(f"Profile created for {profile.name} [{profile.iso639_3 or profile.id}].")
            return profile
        return None


def _choose_candidate(app: App, matches: list[ResolvedLanguage]) -> ResolvedLanguage | None:
    labels = []
    for m in matches[:12]:
        code = m.iso639_3 or m.language_id
        how = f" — matched {m.matched_on.replace('_', ' ')} “{m.matched_text}”" if m.matched_on not in ("name", "code") else ""
        where = f"; {m.region}" if m.region else ""
        labels.append(f"{m.name} [{code}]{where}{how}")
    labels.append("None of these")
    idx = r.choose("Candidates", labels)
    if idx is None or idx == len(labels) - 1:
        return None
    return matches[idx]


# ------------------------------------------------------------------ §2.6 profile step
def profile_step(app: App, profile: Profile, force_menu: bool = False) -> None:
    status = app.profile_service.status(profile)
    wizard = ProfileWizard(app, profile)
    wizard.show_known_missing(status)
    if not status.to_ask and not force_menu:
        r.out("Profile complete.")
        return
    if status.to_ask and not force_menu:
        if not r.ask_yes_no("Complete missing profile information?"):
            r.out("Continuing with the current profile.")
            return
    while True:
        idx = r.choose("Language Profile", [
            "Complete missing information",
            "Review existing profile",
            "Edit profile",
            "Skip and continue collection",
        ])
        status = app.profile_service.status(profile)
        if idx == 0:
            if not status.to_ask:
                r.out("Nothing is missing.")
                continue
            n = wizard.run(status.to_ask, status)
            r.out(f"{n} value(s) recorded.")
            return
        if idx == 1:
            wizard.review()
            continue
        if idx == 2:
            edit_profile(app, profile, wizard)
            continue
        return


def edit_profile(app: App, profile: Profile, wizard: ProfileWizard) -> None:
    from ..profile import schema
    groups = [g.title for g in schema.GROUPS] + ["All fields", "Back"]
    idx = r.choose("Edit profile – choose a section", groups)
    if idx is None or idx == len(groups) - 1:
        return
    status = app.profile_service.status(profile)
    if idx == len(groups) - 2:
        fields = [(g.name, f.name) for g, f in schema.all_fields()]
    else:
        g = schema.GROUPS[idx]
        fields = [(g.name, f.name) for f in g.fields]
    n = wizard.run(fields, status)
    r.out(f"{n} value(s) recorded.")


# ------------------------------------------------------------------ §3 main menu
def main_menu(app: App, profile: Profile) -> None:
    while True:
        idx = r.choose(f"Data Collection\n\nLanguage: {profile.name} [{profile.iso639_3 or profile.id}]", [
            "Online Collection",
            "Offline Collection",
            "Import Files / Folder",
            "View Existing Collection",
            "Language Profile",
            "Exit",
        ])
        if idx == 0:
            online_menu(app, profile)
        elif idx == 1:
            offline_collection(app, profile)
        elif idx == 2:
            import_menu(app, profile)
        elif idx == 3:
            view_collection(app, profile)
        elif idx == 4:
            profile = app.language_service.load(profile.id) or profile
            profile_step(app, profile, force_menu=True)
        else:
            return


# ------------------------------------------------------------------ §4 online
def online_menu(app: App, profile: Profile) -> None:
    while True:
        idx = r.choose("Online Collection", ["Catalogue Search", "Agent Search", "Back"])
        if idx == 0:
            catalogue_search(app, profile)
        elif idx == 1:
            agent_search(app, profile)
        else:
            return


# ------------------------------------------------------------------ §4.1 catalogue search
def catalogue_search(app: App, profile: Profile, assume_yes: bool = False,
                     min_score: int | None = None) -> SessionSummary | None:
    svc = app.catalogue_service
    providers = svc.enabled()
    if not providers:
        r.out("No catalogue providers are enabled. Add one with: aimixe collect catalogue add")
        return None
    r.heading(f"Catalogue Search – {profile.name} [{profile.iso639_3 or profile.id}]")
    for p in providers:
        ok, why = p.available_for(profile)
        r.out(f"  {p.name:18} {p.kind:7} {p.description if ok else '— skipped: ' + why}")
    r.out()
    if not assume_yes:
        if not r.ask_yes_no("Search all enabled catalogues?"):
            raw = r.prompt("Catalogue names to search (comma separated):")
            wanted = {w.strip() for w in raw.split(",") if w.strip()}
            providers = [p for p in providers if p.name in wanted]
            if not providers:
                r.out("Nothing selected.")
                return None
    r.out("Searching …")
    import time as _time
    t0 = _time.time()
    report = svc.search(profile, providers, on_provider=lambda name, n: r.out(f"  {name}: {n} result(s)"))
    r.out(f"  search took {_time.time() - t0:.0f} s")
    for err in report.errors:
        r.out(f"  ! {err}")
    if not report.results and not report.lookups:
        r.out("No results.")
        return None
    r.out()
    rows = []
    for sr in report.results[:60]:
        rows.append([str(sr.relevance.score), sr.relevance.band_label, sr.result.provider,
                     sr.result.title[:70], str(len(sr.result.files)) if sr.result.fetched else "?"])
    if rows:
        r.table(rows, headers=["score", "band", "catalogue", "title", "files"])
    if report.lookups:
        r.out()
        r.out("Places to open in a browser (no machine-readable search):")
        for lk in report.lookups:
            r.out(f"  {lk.provider:14} {lk.landing_url}")
    downloadable = [s for s in report.results if s.action == "download"]
    if not downloadable:
        r.out("\nNothing scored above the relevance threshold; nothing will be downloaded.")
        return None
    threshold = min_score if min_score is not None else int(app.config.get("online", "min_download_score", 50))
    if not assume_yes:
        r.out()
        conf = sum(1 for s in downloadable if s.relevance.score >= app.config.confirmed_at)
        low = sum(1 for s in downloadable if s.relevance.score < threshold)
        r.out(f"{len(downloadable)} result(s) at or above {app.config.review_at}: {conf} confirmed, "
              f"{len(downloadable) - conf} would go to the review queue; {low} below the default minimum of {threshold}.")
        raw = r.prompt(f"Minimum relevance to download and store [{threshold}]:", default=str(threshold))
        threshold = int(raw) if raw.isdigit() else threshold
        if not r.ask_yes_no("Download and store now?"):
            return None
    board = r.ProgressBoard()
    run = svc.collect(profile, report, min_score=threshold, progress=Progress(board.handle),
                      on_outcome=lambda o: board.print_line(_outcome_text(o)), on_message=board.print_line)
    board.finish()
    if run.report.proposals:
        r.out(f"  {run.report.proposals} language fact(s) proposed for review (aimixe collect review).")
    if run.lookup_manifest:
        r.out(f"  lookup links saved to {run.lookup_manifest}")
    summary = app.collection_service.summary(run.session_id)
    print_summary(summary)
    return summary


# ------------------------------------------------------------------ §6 agent search
def agent_search(app: App, profile: Profile, assume_yes: bool = False) -> SessionSummary | None:
    svc = app.agent_service
    name, ok, why = svc.agent_status()
    r.heading(f"Agent Search – {profile.name} [{profile.iso639_3 or profile.id}]")
    r.out(f"Agent provider: {name}" + ("" if ok else f" — not available ({why}); the rule-based agent is used"))
    backends = svc.backends()
    r.out("Web search backends: " + (", ".join(b.name for b in backends) or "none configured"))
    if not backends:
        r.out("Configure search_backends under [agent] in config.toml.")
        return None
    board = r.ProgressBoard()
    runner = svc.runner(profile, backends, progress=Progress(board.handle))
    r.out("Planning queries from the language profile …")
    queries = runner.plan()
    r.out()
    for i, q in enumerate(queries, 1):
        why = f"   ← {q.rationale}" if q.rationale else ""
        r.out(f"  {i:2}. [{q.basis}] {q.text}{why}")
    r.out()
    if not assume_yes:
        extra = r.prompt("Add your own queries (separate with ';'), or blank:")
        for text in [x.strip() for x in extra.split(";") if x.strip()]:
            from ..agent.base import AgentQuery
            queries.append(AgentQuery(text, "user"))
        if not r.ask_yes_no(f"Run {len(queries)} quer{'y' if len(queries) == 1 else 'ies'} now?"):
            return None
    lim = svc.limits()
    r.out(f"Limits: {lim.max_pages} pages, depth {lim.max_depth}, {lim.per_host} per host, {lim.max_files} files, "
          f"{lim.max_rounds} rounds. New names found during the search feed later rounds.")
    run = svc.run(profile, runner, queries, on_message=board.print_line,
                  on_outcome=lambda o: board.print_line(_outcome_text(o)))
    board.finish()
    rep = run.report
    r.out()
    r.out(f"Hits: {rep.hits}   pages fetched: {rep.pages_fetched}   relevant pages: {rep.pages_relevant}   "
          f"files found: {rep.files_found}")
    if rep.learned:
        r.out("Learned during this session (proposed for review, not written to the profile): " + ", ".join(rep.learned[:10]))
    if run.proposals_queued:
        r.out(f"{run.proposals_queued} language fact(s) proposed for review (aimixe collect review).")
    for err in rep.errors[:8]:
        r.out(f"  ! {err}")
    summary = app.collection_service.summary(run.session_id)
    print_summary(summary)
    return summary


# ------------------------------------------------------------------ §8 offline
def offline_collection(app: App, profile: Profile, roots: list[Path] | None = None,
                       mode: str | None = None) -> SessionSummary | None:
    if not roots:
        r.heading("Offline Collection")
        terms = app.collection_service.offline_terms(profile)
        r.out(f"Scanning for {len(terms)} term(s) from the language profile, e.g.: "
              + ", ".join(t.text for t in terms[:8]))
        r.out()
        raw = r.prompt("Folder(s) to scan (separate several with ';'; default: your home folder):",
                       default=str(Path.home()))
        roots = [Path(p.strip()).expanduser() for p in raw.split(";") if p.strip()]
    missing = [p for p in roots if not p.exists()]
    if missing:
        r.out("Not found: " + ", ".join(str(m) for m in missing))
        return None
    interactive_run = mode is None
    mode = mode or _ask_mode(app)
    content = None
    if interactive_run:
        content = r.ask_yes_no("Also look inside text and document files (slower, finds files whose names say nothing)?",
                               default=bool(app.config.get("scan", "content", True)))
    r.out(f"\nScanning {', '.join(str(p) for p in roots)} …")
    board = r.ProgressBoard()
    prog = Progress(board.handle)
    result = app.collection_service.run_offline(
        profile, roots, storage_mode=mode, on_outcome=lambda o: board.print_line(_outcome_text(o)),
        on_progress=lambda n, p, hits: prog.step(files_seen=n, hits=hits, stage="scanning"), content_scan=content)
    board.finish()
    rep = result.scan_report
    if rep:
        r.out(f"\nFiles seen: {rep.files_seen}   matches: {rep.hits}   folders skipped: {rep.dirs_skipped}")
    summary = app.collection_service.summary(result.session_id)
    print_summary(summary)
    return summary


# ------------------------------------------------------------------ §9 import
def import_menu(app: App, profile: Profile) -> None:
    r.heading("Import Files / Folder")
    target = r.prompt("File or folder to import:")
    if not target:
        return
    path = Path(target).expanduser()
    if not path.exists():
        r.out(f"Not found: {path}")
        return
    mode = _ask_mode(app)
    run_import(app, profile, path, mode)


def run_import(app: App, profile: Profile, path: Path, mode: str | None) -> SessionSummary:
    r.out(f"\nImporting {path} ({mode or app.config.storage_mode}) …")
    board = r.ProgressBoard()
    prog = Progress(board.handle)
    result = app.import_service.run(profile, path, mode, on_outcome=lambda o: board.print_line(_outcome_text(o)),
                                    on_progress=lambda i, n: prog.step(import_done=i, import_total=n, stage="importing"))
    board.finish()
    summary = app.collection_service.summary(result.session_id)
    print_summary(summary)
    return summary


def _ask_mode(app: App) -> str:
    default = app.config.storage_mode
    while True:
        ans = r.prompt(f"Storage mode — Copy / Move / Reference [default: {default}]:", default=default).lower()
        if ans in STORAGE_MODES:
            return ans
        r.out("Enter copy, move or reference.")


# ------------------------------------------------------------------ view / summaries
def view_collection(app: App, profile: Profile) -> None:
    rows = app.collection_service.resources_for(profile)
    r.heading(f"Existing Collection – {profile.name} [{profile.iso639_3 or profile.id}]: {len(rows)} resource(s)")
    if not rows:
        return
    table = []
    for row in rows:
        d = dict(row)
        table.append([str(d["id"]), d["original_name"][:48], d["format"], d["category"],
                      (d["types"] or "—")[:30], f"{d['relevance_score']} {d['status']}", str(d["source_count"])])
    r.table(table, headers=["#", "name", "format", "category", "resource type", "relevance", "sources"])
    r.out()
    ans = r.prompt("Resource number for details (blank to go back):")
    if ans.isdigit():
        show_resource(app, int(ans))


def show_resource(app: App, resource_id: int) -> None:
    r.out("Sources:")
    for s in app.collection_service.resource_sources(resource_id):
        d = {k: v for k, v in dict(s).items() if v not in (None, "")}
        r.out("  " + "; ".join(f"{k}={v}" for k, v in d.items() if k not in ("id", "resource_id")))
    ex = app.resources.extractions(resource_id)
    if ex:
        r.out("Extracted:")
        for e in ex:
            r.out(f"  {e['kind']:9} {e['path']}")
    nd = app.resources.near_duplicates(resource_id)
    if nd:
        r.out("Near-duplicates:")
        for n in nd:
            r.out(f"  #{n['other_id']} {n['original_name']} ({n['similarity']:.0%}, {n['method']})")


def _outcome_text(o: PipelineOutcome) -> str:
    label = {"stored": "stored", "duplicate_linked": "duplicate", "uncertain_review": "review",
             "rejected": "skipped", "failed": "FAILED"}[o.status]
    rel = f" {o.relevance}" if o.relevance is not None else ""
    types = f" [{', '.join(o.types[:3])}]" if o.types else ""
    extra = f" — {o.message}" if o.status in ("failed", "duplicate_linked", "rejected") and o.message else ""
    return f"  {label:9}{rel:>4} {o.candidate.display}{types}{extra}"


def _print_outcome(o: PipelineOutcome) -> None:
    r.out(_outcome_text(o))


def print_summary(s: SessionSummary) -> None:
    r.heading(f"Collection Session: {s.id}")
    r.out(f"Language: {s.language_name} [{s.language_id}]")
    r.out(f"Mode: {s.mode}")
    r.out()
    r.out(f"Discovered: {s.discovered}")
    r.out(f"Relevant: {s.relevant}")
    r.out(f"Downloaded: {s.downloaded}")
    r.out(f"Duplicates: {s.duplicates}")
    r.out(f"Failed: {s.failed}")
    r.out(f"Pending review: {s.pending_review}")
    if s.status != "finished":
        r.out(f"Status: {s.status}")
    r.out()


# ------------------------------------------------------------------ catalogue add (guided)
def catalogue_add_wizard() -> dict | None:
    r.heading("Add a catalogue provider")
    name = r.prompt("Name (short, e.g. my_university_repo):")
    if not name:
        return None
    kinds = ["lookup — a URL to open in a browser; nothing is fetched",
             "api_json — a JSON search API, fields mapped by dotted paths",
             "html_links — a web page whose links are collected"]
    k = r.choose("Kind", kinds)
    kind = ["lookup", "api_json", "html_links"][k]
    r.out("URL template. Placeholders: {q} search term, {name} language name, {code} ISO 639-3 code.")
    url = r.prompt("URL template:")
    if not url:
        return None
    cfg: dict = {"name": name, "kind": kind, "url": url}
    asks = r.prompt("Search by name or code? [name]:", default="name").lower()
    cfg["asks_by"] = asks if asks in ("name", "code", "both") else "name"
    what = r.prompt("Short description:")
    if what:
        cfg["what"] = what
    lic = r.prompt("Licence note (optional):")
    if lic:
        cfg["licence_note"] = lic
    if kind == "api_json":
        cfg["items"] = r.prompt("Dotted path to the list of results (e.g. hits.hits, or blank for the root):")
        fields = {}
        for key, hint in (("title", "title"), ("url", "landing page URL"), ("download", "download URL(s), e.g. files[].links.self"),
                          ("description", "description"), ("licence", "licence"), ("date", "date"),
                          ("types", "resource type"), ("language", "language")):
            v = r.prompt(f"Path for {hint} (blank to skip):")
            if v:
                fields[key] = v
        cfg["fields"] = fields
    elif kind == "html_links":
        pat = r.prompt("Regular expression a link must match (blank for all links):")
        if pat:
            cfg["link_pattern"] = pat
    return cfg


# ------------------------------------------------------------------ entry
def run_interactive(app: App, preset_language: str | None = None, assume_yes: bool = False) -> int:
    try:
        profile = pick_language(app, preset_language, assume_yes)
        if profile is None:
            return 0
        profile_step(app, profile)
        profile = app.language_service.load(profile.id) or profile
        main_menu(app, profile)
        return 0
    except Abort:
        r.out("Bye.")
        return 0


__all__ = ["run_interactive", "pick_language", "profile_step", "offline_collection", "run_import", "catalogue_search", "agent_search",
           "print_summary", "run_review"]
