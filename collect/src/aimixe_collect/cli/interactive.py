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
from .render import Abort, Back
from .review_ui import run_review


def _header(app: App, profile: Profile | None) -> None:
    if profile is None:
        r.header()
        return
    r.header(profile.name, profile.iso639_3 or profile.id, app.resources.count_for_language(profile.id),
             len(app.review_service.pending(profile.id)))


WELCOME = """Welcome. AImixE collects language resources three ways: online (catalogues and an agent
searching the web), offline (scanning folders on this machine) and by direct import. Every file
is hashed, classified, stored unchanged and indexed with where it came from. Start by naming a
language; the profile you build for it steers every search."""


# ------------------------------------------------------------------ home screen
def _language_state(app: App, row) -> tuple[str, str]:
    """(status tags, suggested next step) for one stored language."""
    lid = row["id"]
    resources = app.resources.count_for_language(lid)
    pending = len(app.review_service.pending(lid))
    profile = app.language_service.load(lid)
    to_ask = len(app.profile_service.status(profile).to_ask) if profile else 0
    tags = []
    if row["identifier_type"] == "local":
        tags.append(r.c("local id", "yellow"))
    tags.append(f"{resources} resource(s)")
    if pending:
        tags.append(r.c(f"{pending} to review", "yellow"))
    last = app.sessions.last_for_language(lid)
    if last is not None:
        tags.append(r.c(f"last: {_when(last['started_at'])} · {last['mode']}", "grey"))
    else:
        tags.append(r.c("never collected", "grey"))
    if pending:
        step = f"go through what is waiting ({pending} item(s) in the review queue)"
    elif resources == 0:
        step = "start collecting: online, offline or import"
    elif to_ask > 12:
        step = f"complete the language profile ({to_ask} field(s) still missing)"
    else:
        step = "collect more, or view the existing collection"
    return "  ".join(tags), step


def _when(iso: str) -> str:
    """'today 14:02', 'yesterday', '3 days ago' or the date, from an ISO timestamp (UTC)."""
    from datetime import datetime, timezone
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return iso[:10]
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    local = t.astimezone()
    days = (datetime.now(tz=local.tzinfo).date() - local.date()).days
    if days == 0:
        return f"today {local:%H:%M}"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    return f"{local:%Y-%m-%d}"


def home_screen(app: App) -> list:
    """List the languages already entered, each with its state and a next step. Returns the rows."""
    rows = list(app.languages.list())
    r.title_bar()
    if not rows:
        r.note(WELCOME)
        r.out()
        return rows
    width = max(len(x["name"]) for x in rows)
    for i, row in enumerate(rows, 1):
        tags, step = _language_state(app, row)
        code = row["iso639_3"] or row["id"]
        r.out(f"  {r.c(str(i), 'cyan', 'bold'):>2}  {r.c(row['name'].ljust(width), 'bold')}  {r.c(code, 'grey')}  {tags}")
        r.hint(step, indent=6)
    r.out()
    r.note("  a number opens that language · a name or ISO code starts another · q leaves")
    r.out()
    return rows


# ------------------------------------------------------------------ §1 language step
def show_detected(m: ResolvedLanguage) -> None:
    r.heading("Language detected")
    r.out(f"Name: {r.c(m.name, 'bold')}")
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
            rows = home_screen(app)
            query = r.prompt("Enter language name or ISO 639-3 code:",
                             help="A language name (Tangsa), an ISO 639-3 code (nst), an alternative name or a dialect name, "
                                  "or the number of a language listed above. The local registry is searched first, "
                                  "then the bundled ISO 639-3 / Glottolog tables.")
            if not query:
                continue
            if query.isdigit() and 1 <= int(query) <= len(rows):
                profile = app.language_service.load(rows[int(query) - 1]["id"])
                if profile is not None:
                    return profile
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
    r.title_bar(f"Language Profile · {profile.name} [{profile.iso639_3 or profile.id}]")
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
        ], descriptions=[f"{len(status.to_ask)} field(s) missing or uncertain, asked group by group; blank skips a field",
                         "every field with its value and where each value came from",
                         "change any field, one section or all of them", ""])
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
MAIN_HELP = ("Online: search catalogues (Glottolog, Zenodo, Internet Archive …) or let an agent search the web. "
             "Offline: scan folders on this machine for the profile's names. Import: add a file or folder directly. "
             "View: what is stored for this language. Profile: complete or edit the language profile.")


def main_menu(app: App, profile: Profile) -> None:
    while True:
        profile = app.language_service.load(profile.id) or profile
        _header(app, profile)
        try:
            pending = len(app.review_service.pending(profile.id))
            idx = r.choose(f"Data Collection\n\nLanguage: {profile.name} [{profile.iso639_3 or profile.id}]", [
                "Online Collection",
                "Offline Collection",
                "Import Files / Folder",
                "View Existing Collection",
                "Language Profile",
                "Exit",
            ], help=MAIN_HELP, descriptions=[
                "catalogues and archives, or an agent searching the web",
                "scan folders on this machine for files about the language",
                "add a file or folder you already have",
                f"{app.resources.count_for_language(profile.id)} resource(s) stored"
                + (r.c(f" · {pending} waiting in the review queue", "yellow") if pending else ""),
                "complete, review or edit the language profile",
                "back to the list of languages",
            ])
        except Back:
            return
        try:
            if idx == 0:
                online_menu(app, profile)
            elif idx == 1:
                offline_collection(app, profile)
            elif idx == 2:
                import_menu(app, profile)
            elif idx == 3:
                view_collection(app, profile)
            elif idx == 4:
                profile_step(app, profile, force_menu=True)
            else:
                return
        except Back:
            continue


def run_loop(app: App, preset_language: str | None = None, assume_yes: bool = False) -> int:
    """Home screen → language → menu, and back to the home screen on Exit; q leaves."""
    preset = preset_language
    while True:
        profile = pick_language(app, preset, assume_yes)
        preset = None
        if profile is None:
            return 0
        profile_step(app, profile)
        profile = app.language_service.load(profile.id) or profile
        main_menu(app, profile)


# ------------------------------------------------------------------ §4 online
def online_menu(app: App, profile: Profile) -> None:
    while True:
        idx = r.choose("Online Collection", ["Catalogue Search", "Agent Search", "Back"],
                       descriptions=["Glottolog, Zenodo, Internet Archive, Kaipuleohone, plus lookup links for OLAC, ELAR, PARADISEC, Pangloss",
                                     "queries planned from the profile; rule-based or a model CLI you choose", ""],
                       help="Catalogue Search asks known archives and repositories with the whole profile. "
                            "Agent Search plans web queries from the profile, follows pages and learns new names.")
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
    r.title_bar(f"Catalogue Search · {profile.name} [{profile.iso639_3 or profile.id}]")
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
        rows.append([r.score_text(sr.relevance.score), sr.relevance.band_label, sr.result.provider,
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
    print_summary(summary, app)
    return summary


# ------------------------------------------------------------------ §6 agent search
def agent_search(app: App, profile: Profile, assume_yes: bool = False) -> SessionSummary | None:
    svc = app.agent_service
    name, ok, why = svc.agent_status()
    r.title_bar(f"Agent Search · {profile.name} [{profile.iso639_3 or profile.id}]")
    r.out(f"Agent provider: {name}" + ("" if ok else f" — not available ({why}); the rule-based agent is used"))
    if not assume_yes and r.ask_yes_no("Use a different agent provider?", default=False):
        choose_agent_provider(app)
        name, ok, why = svc.agent_status()
        r.out(f"Agent provider: {name}" + ("" if ok else f" — not available ({why}); the rule-based agent is used"))
    backends = svc.backends()
    r.out("Web search engines: " + (", ".join(b.name for b in backends) or r.c("none usable", "yellow")))
    if not assume_yes and r.ask_yes_no("Change the search engines?", default=not backends,
                                       help="Pick which engines Agent Search asks, in order. Engines that need an API key "
                                            "show what to set. Add your own with: aimixe collect search add"):
        choose_search_engines(app)
        backends = svc.backends()
        r.out("Web search engines: " + (", ".join(b.name for b in backends) or r.c("none usable", "yellow")))
    if not backends:
        r.out("No usable search engine. Add or enable one: aimixe collect search list | add | test <name>")
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
    print_summary(summary, app)
    return summary


def choose_agent_provider(app: App) -> str | None:
    """Pick the agent provider (rule-based or an installed model CLI) and save it to config.toml."""
    choices = app.agent_service.choices()
    labels = []
    for c in choices:
        mark = "● " if c["current"] else "  "
        avail = "" if c["installed"] else "   (not installed on this machine)"
        labels.append(f"{mark}{c['name']:12} {c['what']}{avail}")
    labels.append("  Keep current")
    idx = r.choose("Agent provider", labels)
    if idx is None or idx == len(labels) - 1:
        return None
    chosen = choices[idx]
    if not chosen["installed"]:
        r.out(f"{chosen['name']} is not on PATH; the rule-based agent will be used until it is installed.")
    if chosen["name"] != "rule_based":
        r.out("Note: with a model provider the language profile and the text of visited pages are sent to that tool.")
    app.agent_service.set_provider(chosen["name"])
    r.out(f"Saved: provider = \"{chosen['name']}\" in {app.paths.config / 'config.toml'}")
    return chosen["name"]


def choose_search_engines(app: App) -> list[str] | None:
    """Pick the engines Agent Search uses (numbers in order); saved to config.toml."""
    engines = app.agent_service.engines()
    r.heading("Search engines")
    for i, e in enumerate(engines, 1):
        mark = r.c("●", "green") if e["enabled"] else " "
        avail = "" if e["available"] else r.c(f"  ⚠ {e['why']}", "yellow")
        flag = "" if e["verified"] else r.c("  (unverified)", "grey")
        r.out(f"{mark}{i:2}. {e['name']:12} {r.c(e['kind'], 'grey')}  {e['what']}{flag}{avail}")
        if e["region"]:
            r.hint(f"region: {e['region']}", indent=6)
    r.out()
    r.note("  Enter the numbers to use, in the order to ask them (e.g. 3 1 2). Blank keeps the current choice.")
    ans = r.prompt("Engines:", help="Numbers separated by spaces or commas. An engine missing its key is skipped at run time "
                                     "until the key is set under [agent.search_keys] in config.toml.")
    if not ans:
        return None
    picks = []
    for tok in ans.replace(",", " ").split():
        if tok.isdigit() and 1 <= int(tok) <= len(engines):
            picks.append(engines[int(tok) - 1]["name"])
        elif tok in {e["name"] for e in engines}:
            picks.append(tok)
    if not picks:
        r.out("Nothing recognised; keeping the current choice.")
        return None
    app.agent_service.set_backends(picks)
    r.out(f"Saved: search_backends = {picks} in {app.paths.config / 'config.toml'}")
    return picks


def search_engine_add_wizard() -> dict | None:
    r.heading("Add a search engine")
    name = r.prompt("Name (short, e.g. my_searxng):")
    if not name:
        return None
    kinds = ["json — a JSON API (SearXNG, Brave, Google Programmable Search, SerpAPI …)",
             "rss — an RSS or Atom feed of results",
             "html — a results web page, links picked out with a regular expression (best effort)"]
    kind = ["json", "rss", "html"][r.choose("Kind", kinds)]
    r.out("URL template. Placeholders: {q} the query, {key} an API key, {cx} an extra id, {lang} a language code.")
    url = r.prompt("URL template:")
    if not url:
        return None
    cfg: dict = {"name": name, "kind": kind, "url": url}
    what = r.prompt("Short description (where it works, who runs it):")
    if what:
        cfg["what"] = what
    if r.ask_yes_no("Does it need an API key?", default=False):
        cfg["needs_key"] = True
        hdr = r.prompt("Header name for the key, if it is sent as a header (blank when {key} is in the URL):")
        if hdr:
            cfg["key_header"] = hdr
        r.note(f"  Put the key under [agent.search_keys] in config.toml as {name} = \"…\"")
    if kind == "json":
        cfg["items"] = r.prompt("Dotted path to the result list (e.g. results, web.results; blank for the root):")
        fields = {}
        for key, hint in (("url", "result URL"), ("title", "title"), ("snippet", "snippet/description")):
            v = r.prompt(f"Path for {hint} (blank to skip):")
            if v:
                fields[key] = v
        cfg["fields"] = fields
    elif kind == "html":
        pat = r.prompt("Regular expression: first group = URL, optional second group = title (blank for every link):")
        if pat:
            cfg["link_pattern"] = pat
        blocked = r.prompt("Text that marks a bot-check page (optional, e.g. captcha|验证码):")
        if blocked:
            cfg["blocked_pattern"] = blocked
    if r.ask_yes_no("Remove phrase quotes from queries for this engine?", default=False):
        cfg["strip_quotes"] = True
    return cfg


# ------------------------------------------------------------------ §8 offline
def offline_collection(app: App, profile: Profile, roots: list[Path] | None = None,
                       mode: str | None = None) -> SessionSummary | None:
    if not roots:
        r.title_bar(f"Offline Collection · {profile.name} [{profile.iso639_3 or profile.id}]")
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
    print_summary(summary, app)
    return summary


# ------------------------------------------------------------------ §9 import
def import_menu(app: App, profile: Profile) -> None:
    r.title_bar(f"Import Files / Folder · {profile.name} [{profile.iso639_3 or profile.id}]")
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
    print_summary(summary, app)
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
    r.title_bar(f"Existing Collection · {profile.name} [{profile.iso639_3 or profile.id}]")
    r.out(f"  {r.c(str(len(rows)), 'bold')} resource(s)")
    r.out()
    if not rows:
        return
    table = []
    for row in rows:
        d = dict(row)
        table.append([str(d["id"]), d["original_name"], d["format"], d["category"],
                      (d["types"] or "—"), f"{r.score_text(d['relevance_score'])} {d['status']}", str(d["source_count"])])
    r.table(table, headers=["#", "name", "format", "category", "resource type", "relevance", "sources"])
    r.out()
    ids = {str(d["id"]) for d in map(dict, rows)}
    while True:
        ans = r.prompt("Resource number for details (blank to go back):",
                       help="Type the number in the first column to see its provenance, extracted files and near-duplicates.")
        if not ans or ans.lower() in ("b", "back"):
            return
        if ans in ids:
            show_resource(app, int(ans))
        else:
            r.out("No such resource number.")


def show_resource(app: App, resource_id: int) -> None:
    row = app.conn.execute("SELECT * FROM resource WHERE id=?", (resource_id,)).fetchone()
    if row is not None:
        r.heading(f"#{row['id']} {row['original_name']}")
        r.out(f"  stored at  {row['stored_path']}")
        r.out(f"  sha256     {row['sha256']}")
        r.out(f"  format     {row['format']} · {row['category']} · {row['size']} bytes · {row['storage_mode']}")
        types = app.conn.execute("SELECT type, confidence, source FROM resource_type WHERE resource_id=? ORDER BY confidence DESC",
                                 (resource_id,)).fetchall()
        if types:
            r.out("  types      " + ", ".join(f"{t['type']} ({t['confidence']:.2f}, {t['source']})" for t in types))
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
    word, colour = r.STATUS_STYLE[o.status]
    label = r.c(f"{word:9}", colour)
    rel = f" {r.score_text(o.relevance)}" if o.relevance is not None else "    "
    types = f" [{', '.join(o.types[:3])}]" if o.types else ""
    extra = f" — {o.message}" if o.status in ("failed", "duplicate_linked", "rejected") and o.message else ""
    return f"  {label}{rel} {o.candidate.display}{types}{extra}"


def _print_outcome(o: PipelineOutcome) -> None:
    r.out(_outcome_text(o))


def print_summary(s: SessionSummary, app: App | None = None) -> None:
    r.heading(f"Collection Session: {s.id}")
    r.out(f"Language: {s.language_name} [{s.language_id}]")
    r.out(f"Mode: {s.mode}")
    r.out()
    r.out(f"Discovered: {r.c(str(s.discovered), 'bold')}")
    r.out(f"Relevant: {r.c(str(s.relevant), 'bold')}")
    r.out(f"Downloaded: {r.c(str(s.downloaded), 'green', 'bold')}")
    r.out(f"Duplicates: {s.duplicates}")
    r.out(f"Failed: {r.c(str(s.failed), 'red') if s.failed else '0'}")
    r.out(f"Pending review: {r.c(str(s.pending_review), 'yellow') if s.pending_review else '0'}")
    if s.status != "finished":
        r.out(f"Status: {s.status}")
    extras = []
    if s.started_at and s.finished_at:
        from datetime import datetime
        from ..progress import human_time
        try:
            secs = (datetime.fromisoformat(s.finished_at) - datetime.fromisoformat(s.started_at)).total_seconds()
            extras.append(f"took {human_time(secs)}")
        except ValueError:
            pass
    if app is not None:
        from ..progress import human_bytes
        b = app.resources.session_bytes(s.id)
        if b:
            extras.append(f"{human_bytes(b)} stored")
    if extras:
        r.note("  " + " · ".join(extras))
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
        return run_loop(app, preset_language, assume_yes)
    except (Abort, Back):
        r.out("Bye.")
        return 0


__all__ = ["run_interactive", "pick_language", "profile_step", "offline_collection", "run_import", "catalogue_search", "agent_search", "choose_agent_provider", "choose_search_engines", "search_engine_add_wizard",
           "print_summary", "run_review"]
