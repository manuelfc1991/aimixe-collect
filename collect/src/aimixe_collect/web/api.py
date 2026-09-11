"""JSON API over the application services (specification §19: presentation only).

Every handler opens its own ``App`` (SQLite connections are per thread) and closes it.
Long-running collection runs become jobs; the page polls them.
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from ..agent.base import AgentQuery
from ..discovery.candidate import PipelineOutcome
from ..language.registry import Registry, load_registry
from ..profile import schema
from ..profile.parse import parse_form
from ..progress import Progress, human_bytes, human_rate, human_time
from ..services.app import App
from .jobs import Job, JobManager


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _jsonable(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if hasattr(obj, "keys") and hasattr(obj, "__getitem__"):   # sqlite3.Row
        return {k: obj[k] for k in obj.keys()}
    return obj


def outcome_json(o: PipelineOutcome) -> dict[str, Any]:
    return {"status": o.status, "name": o.candidate.display, "relevance": o.relevance, "band": o.band,
            "types": o.types, "message": o.message, "resource_id": o.resource_id,
            "method": o.candidate.method, "url": o.candidate.url}


class Api:
    def __init__(self, home: Path | None, jobs: JobManager):
        self.home = home
        self.jobs = jobs
        self.registry: Registry = load_registry()

    def app(self) -> App:
        return App(self.home, registry=self.registry)

    # ------------------------------------------------------------------ dispatch
    def handle(self, method: str, path: str, query: dict[str, str], body: dict[str, Any]) -> Any:
        parts = [p for p in path.split("/") if p]
        if not parts or parts[0] != "api":
            raise ApiError(404, "not found")
        parts = parts[1:]
        with self.app() as app:
            return self._route(app, method, parts, query, body)

    def _route(self, app: App, method: str, parts: list[str], q: dict[str, str], body: dict[str, Any]) -> Any:
        head = parts[0] if parts else ""
        if head == "status" and method == "GET":
            name, ok, why = app.agent_service.agent_status()
            return {"home": str(app.paths.root), "languages": [_jsonable(r) for r in app.languages.list()],
                    "agent": {"name": name, "available": ok, "why": why,
                              "installed": [{"name": n, "installed": i, "what": w} for n, i, w in app.agent_service.installed()]},
                    "backends": [b.name for b in app.agent_service.backends()],
                    "catalogues": [{"name": e.name, "kind": e.provider.kind, "enabled": e.enabled,
                                    "builtin": e.source == "builtin", "what": e.provider.description}
                                   for e in app.catalogue_service.list()],
                    "config": {"review_at": app.config.review_at, "confirmed_at": app.config.confirmed_at,
                               "storage_mode": app.config.storage_mode,
                               "min_download_score": app.config.get("online", "min_download_score", 50)},
                    "pending_review": len(app.review_service.pending())}
        if head == "schema" and method == "GET":
            return {"groups": [{"name": g.name, "title": g.title, "progress_label": g.progress_label,
                                "fields": [asdict(f) for f in g.fields]} for g in schema.GROUPS],
                    "states": schema.AVAILABILITY_STATES}
        if head == "resolve" and method == "GET":
            res = app.language_service.resolve(q.get("q", ""))
            return {"query": res.query, "status": res.status,
                    "matches": [{"index": i, "language_id": m.language_id, "name": m.name, "iso639_3": m.iso639_3,
                                 "identifier_type": m.identifier_type, "matched_on": m.matched_on,
                                 "matched_text": m.matched_text, "score": m.score, "source": m.source,
                                 "alternative_names": m.alternative_names, "region": m.region,
                                 "family": m.record.family if m.record else None}
                                for i, m in enumerate(res.matches)]}
        if head == "languages":
            return self._languages(app, method, parts[1:], q, body)
        if head == "resources" and len(parts) == 2 and method == "GET":
            return self._resource(app, int(parts[1]))
        if head == "sessions" and len(parts) == 2 and method == "GET":
            s = app.history_service.get(parts[1])
            if s is None:
                raise ApiError(404, "no such session")
            return {"session": _jsonable(s), "events": [_jsonable(e) for e in app.history_service.events(parts[1])]}
        if head == "history" and method == "GET":
            return {"sessions": [_jsonable(s) for s in app.history_service.list(q.get("language"))]}
        if head == "review":
            return self._review(app, method, parts[1:], q, body)
        if head == "catalogues":
            return self._catalogues(app, method, parts[1:], body)
        if head == "jobs":
            return self._jobs(app, method, parts[1:], body)
        if head == "agent" and parts[1:] == ["engines"]:
            if method == "GET":
                return {"engines": app.agent_service.engines()}
            if method == "POST":
                try:
                    if "enabled" in body:
                        return {"ok": True, "enabled": app.agent_service.set_backends([str(n) for n in body["enabled"]])}
                    path = app.agent_service.add_engine(body.get("engine") or {})
                    return {"ok": True, "path": str(path)}
                except ValueError as exc:
                    raise ApiError(400, str(exc))
        if head == "agent" and len(parts) == 3 and parts[1] == "engines" and method == "DELETE":
            try:
                return {"ok": True, "message": app.agent_service.remove_engine(parts[2])}
            except ValueError as exc:
                raise ApiError(404, str(exc))
        if head == "agent" and len(parts) == 4 and parts[1] == "engines" and parts[3] == "test" and method == "GET":
            try:
                hits = app.agent_service.test_engine(parts[2], q.get("q", "language documentation"))
            except ValueError as exc:
                raise ApiError(404, str(exc))
            except Exception as exc:
                raise ApiError(502, f"{parts[2]}: {exc}")
            return {"hits": [{"url": h.url, "title": h.title, "snippet": h.snippet} for h in hits]}
        if head == "agent" and parts[1:] == ["provider"]:
            if method == "GET":
                return {"choices": app.agent_service.choices()}
            if method == "POST":
                try:
                    return {"ok": True, "provider": app.agent_service.set_provider(str(body.get("provider", "")))}
                except ValueError as exc:
                    raise ApiError(400, str(exc))
        raise ApiError(404, f"no route for {method} /api/{'/'.join(parts)}")

    # ------------------------------------------------------------------ languages / profile
    def _languages(self, app: App, method: str, parts: list[str], q: dict[str, str], body: dict[str, Any]) -> Any:
        if not parts and method == "GET":
            return {"languages": [_jsonable(r) for r in app.languages.list()]}
        if parts == ["open"] and method == "POST":
            res = app.language_service.resolve(body.get("query", ""))
            idx = int(body.get("index", 0))
            if not res.matches or idx >= len(res.matches):
                raise ApiError(400, "no such candidate")
            profile, created = app.language_service.open_from_resolution(res.matches[idx])
            return {"language_id": profile.id, "created": created}
        if parts == ["create"] and method == "POST":
            name = (body.get("name") or "").strip()
            if not name:
                raise ApiError(400, "a name is required")
            code = (body.get("code") or "").strip() or None
            if code and not app.registry.by_code(code):
                code = None
            profile = app.language_service.create_local(name, code)
            return {"language_id": profile.id, "created": True}
        if not parts:
            raise ApiError(405, "method not allowed")
        lid = parts[0]
        profile = app.language_service.load(lid)
        if profile is None:
            raise ApiError(404, f"no language {lid}")
        rest = parts[1:]
        if not rest and method == "GET":
            st = app.profile_service.status(profile)
            return {"profile": profile.to_json(),
                    "status": {"known": st.known, "missing": st.missing, "uncertain": st.uncertain,
                               "contradictory": st.contradictory, "to_ask": st.to_ask,
                               "groups": {g.name: st.group_state(g.name) for g in schema.GROUPS}},
                    "resource_count": app.resources.count_for_language(lid),
                    "pending_review": len(app.review_service.pending(lid)),
                    "offline_terms": [t.text for t in app.collection_service.offline_terms(profile)][:40]}
        if rest == ["profile"] and method == "POST":
            group, fname = body.get("group"), body.get("field")
            try:
                spec = schema.field_spec(group, fname)
            except KeyError:
                raise ApiError(400, "unknown field")
            value = parse_form(spec, body.get("form") or {}, scripts_lookup=app.registry.script)
            if value is None:
                raise ApiError(400, "nothing to record")
            app.profile_service.set_value(profile, group, fname, value)
            return {"ok": True, "value": value}
        if rest == ["profile", "prefer"] and method == "POST":
            app.profile_service.prefer(profile, body["group"], body["field"], int(body["value_id"]))
            return {"ok": True}
        if rest == ["resources"] and method == "GET":
            rows = app.collection_service.resources_for(profile)
            return {"resources": [_jsonable(r) for r in rows]}
        if rest == ["agent", "plan"] and method == "GET":
            svc = app.agent_service
            name, ok, why = svc.agent_status()
            runner = svc.runner(profile)
            queries = runner.plan()
            lim = svc.limits()
            return {"agent": {"name": name, "available": ok, "why": why}, "backends": [b.name for b in runner.backends],
                    "queries": [asdict(x) for x in queries], "limits": asdict(lim)}
        raise ApiError(404, "no such language route")

    def _resource(self, app: App, rid: int) -> Any:
        row = app.conn.execute("SELECT * FROM resource WHERE id=?", (rid,)).fetchone()
        if row is None:
            raise ApiError(404, "no such resource")
        return {"resource": _jsonable(row),
                "languages": [_jsonable(r) for r in app.conn.execute("SELECT * FROM resource_language WHERE resource_id=?", (rid,))],
                "types": [_jsonable(r) for r in app.conn.execute("SELECT type, confidence, source FROM resource_type WHERE resource_id=? ORDER BY confidence DESC", (rid,))],
                "sources": [_jsonable(r) for r in app.resources.sources(rid)],
                "metadata": [_jsonable(r) for r in app.conn.execute("SELECT key, value, extracted_by FROM resource_metadata WHERE resource_id=? ORDER BY key", (rid,))],
                "extractions": [_jsonable(r) for r in app.resources.extractions(rid)],
                "near_duplicates": [_jsonable(r) for r in app.resources.near_duplicates(rid)]}

    # ------------------------------------------------------------------ review
    def _review(self, app: App, method: str, parts: list[str], q: dict[str, str], body: dict[str, Any]) -> Any:
        if not parts and method == "GET":
            return {"items": [_jsonable(i) for i in app.review_service.pending(q.get("language") or None)]}
        if len(parts) == 2 and method == "POST":
            item_id, action = int(parts[0]), parts[1]
            items = {i.id: i for i in app.review_service.pending()}
            item = items.get(item_id)
            if item is None:
                raise ApiError(404, "no such pending item")
            if action == "accept":
                app.review_service.accept(item)
            elif action == "reject":
                app.review_service.reject(item)
            elif action == "skip":
                app.review_service.skip(item)
            else:
                raise ApiError(400, "unknown action")
            return {"ok": True}
        if len(parts) == 2 and parts[1] == "source" and method == "GET":
            items = {i.id: i for i in app.review_service.pending()}
            item = items.get(int(parts[0]))
            if item is None:
                raise ApiError(404, "no such pending item")
            return {"text": app.review_service.source_text(item)}
        raise ApiError(404, "no such review route")

    # ------------------------------------------------------------------ catalogues
    def _catalogues(self, app: App, method: str, parts: list[str], body: dict[str, Any]) -> Any:
        svc = app.catalogue_service
        if not parts and method == "GET":
            return {"catalogues": [{"name": e.name, "kind": e.provider.kind, "mode": getattr(e.provider, "mode", "python"),
                                    "enabled": e.enabled, "source": e.source, "what": e.provider.description,
                                    "licence_note": e.provider.licence_note, "asks_by": e.provider.asks_by,
                                    "needs_code": e.provider.needs_code} for e in svc.list()],
                    "errors": svc.registry.errors}
        if not parts and method == "POST":
            try:
                path = svc.add(body)
            except (ValueError, KeyError) as exc:
                raise ApiError(400, f"invalid catalogue: {exc}")
            return {"ok": True, "path": str(path)}
        if len(parts) == 1 and method == "DELETE":
            try:
                return {"ok": True, "message": svc.remove(parts[0])}
            except ValueError as exc:
                raise ApiError(404, str(exc))
        raise ApiError(404, "no such catalogue route")

    # ------------------------------------------------------------------ jobs
    def _jobs(self, app: App, method: str, parts: list[str], body: dict[str, Any]) -> Any:
        if not parts and method == "GET":
            return {"jobs": [j.to_json() for j in self.jobs.list()]}
        if len(parts) == 1 and method == "GET":
            job = self.jobs.get(parts[0])
            if job is None:
                raise ApiError(404, "no such job")
            return job.to_json()
        if not parts and method == "POST":
            return self._start_job(body)
        raise ApiError(404, "no such job route")

    def _start_job(self, body: dict[str, Any]) -> Any:
        kind = body.get("kind")
        lid = body.get("language_id")
        params = body.get("params") or {}
        if kind not in ("import", "offline", "catalogue_search", "catalogue_collect", "agent_search", "profile_enrich"):
            raise ApiError(400, f"unknown job kind {kind!r}")
        if not lid:
            raise ApiError(400, "language_id is required")

        def work(job: Job) -> Any:
            with self.app() as app:
                profile = app.language_service.load(lid)
                if profile is None:
                    raise ApiError(404, f"no language {lid}")
                out = lambda o: job.say(_outcome_line(o))

                def on_event(ev: dict) -> None:
                    job.progress = {"counters": ev.get("counters", {}), "active": ev.get("active", []),
                                    "stage": ev.get("counters", {}).get("stage")}
                    if ev.get("kind") == "done":
                        job.say((f"✓ {ev['name']}  {human_bytes(ev['bytes'])} in {human_time(ev['elapsed'])} "
                                 f"({human_rate(ev['speed'])})") if ev.get("ok") else f"✗ {ev['name']}  {ev.get('message', '')[:120]}")
                prog = Progress(on_event)
                if kind == "import":
                    path = Path(params.get("path", "")).expanduser()
                    if not path.exists():
                        raise ApiError(400, f"not found: {path}")
                    job.say(f"Importing {path} …")
                    res = app.import_service.run(profile, path, params.get("mode") or None, on_outcome=out,
                                                 on_progress=lambda i, n: prog.step(import_done=i, import_total=n, stage="importing"))
                    return {"session": _jsonable(app.collection_service.summary(res.session_id)),
                            "outcomes": [outcome_json(o) for o in res.outcomes]}
                if kind == "offline":
                    roots = [Path(p).expanduser() for p in params.get("roots", []) if p.strip()]
                    missing = [str(r) for r in roots if not r.exists()]
                    if not roots or missing:
                        raise ApiError(400, "folder(s) not found: " + ", ".join(missing or ["(none given)"]))
                    job.say(f"Scanning {', '.join(str(r) for r in roots)} …")
                    res = app.collection_service.run_offline(
                        profile, roots, storage_mode=params.get("mode") or None, on_outcome=out,
                        on_progress=lambda n, p, hits: prog.step(files_seen=n, hits=hits, stage="scanning"),
                        content_scan=params.get("content"))
                    rep = res.scan_report
                    return {"session": _jsonable(app.collection_service.summary(res.session_id)),
                            "outcomes": [outcome_json(o) for o in res.outcomes],
                            "scan": {"files_seen": rep.files_seen, "hits": rep.hits, "dirs_skipped": rep.dirs_skipped} if rep else None}
                if kind == "catalogue_search":
                    svc = app.catalogue_service
                    wanted = set(params.get("providers") or [])
                    providers = [p for p in svc.enabled() if not wanted or p.name in wanted]
                    job.say("Searching " + ", ".join(p.name for p in providers) + " …")
                    report = svc.search(profile, providers, on_provider=lambda n, c: job.say(f"{n}: {c} result(s)"))
                    job.keep = report
                    return {"results": [{"index": i, "score": s.relevance.score, "band": s.relevance.band_label,
                                         "provider": s.result.provider, "title": s.result.title,
                                         "url": s.result.landing_url, "action": s.action,
                                         "reasons": s.relevance.reasons[:4], "licence": s.result.licence}
                                        for i, s in enumerate(report.results)],
                            "lookups": [{"provider": l.provider, "title": l.title, "url": l.landing_url} for l in report.lookups],
                            "errors": report.errors, "unavailable": report.unavailable}
                if kind == "catalogue_collect":
                    src = self.jobs.get(params.get("search_job", ""))
                    if src is None or src.keep is None:
                        raise ApiError(400, "run a catalogue search first")
                    job.say("Downloading and storing …")
                    run = app.catalogue_service.collect(profile, src.keep, min_score=int(params.get("min_score", 30)),
                                                        on_outcome=out, on_message=job.say, progress=prog)
                    return {"session": _jsonable(app.collection_service.summary(run.session_id)),
                            "outcomes": [outcome_json(o) for o in run.outcomes],
                            "proposals": run.report.proposals,
                            "lookup_manifest": str(run.lookup_manifest) if run.lookup_manifest else None}
                if kind == "profile_enrich":
                    counts = app.agent_service.propose_profile(profile, on_message=job.say,
                                                               max_pages=int(params.get("max_pages", 6)))
                    return counts
                if kind == "agent_search":
                    svc = app.agent_service
                    runner = svc.runner(profile, progress=prog)
                    queries = [AgentQuery(x["text"], x.get("basis", "user"), x.get("rationale", ""))
                               for x in params.get("queries", []) if x.get("text")]
                    if not queries:
                        queries = runner.plan()
                    else:
                        runner.report.queries = list(queries)
                    job.say(f"Running {len(queries)} queries with {runner.agent.name} …")
                    run = svc.run(profile, runner, queries, on_message=job.say, on_outcome=out)
                    rep = run.report
                    return {"session": _jsonable(app.collection_service.summary(run.session_id)),
                            "outcomes": [outcome_json(o) for o in run.outcomes],
                            "hits": rep.hits, "pages_fetched": rep.pages_fetched, "pages_relevant": rep.pages_relevant,
                            "files_found": rep.files_found, "learned": rep.learned,
                            "proposals_queued": run.proposals_queued, "errors": rep.errors[:20]}
            return None

        job = self.jobs.start(kind, lid, work)
        return {"job_id": job.id}


def _outcome_line(o: PipelineOutcome) -> str:
    label = {"stored": "stored", "duplicate_linked": "duplicate", "uncertain_review": "review",
             "rejected": "skipped", "failed": "FAILED"}[o.status]
    rel = f" {o.relevance}" if o.relevance is not None else ""
    types = f" [{', '.join(o.types[:3])}]" if o.types else ""
    extra = f" — {o.message}" if o.status in ("failed", "duplicate_linked", "rejected") and o.message else ""
    return f"{label:9}{rel:>4} {o.candidate.display}{types}{extra}"


def dumps(obj: Any) -> bytes:
    return json.dumps(_jsonable(obj), ensure_ascii=False, default=str).encode("utf-8")
