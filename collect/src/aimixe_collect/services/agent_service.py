"""Agent Search as an application service (specification §6, §18, §20)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..agent.base import AgentProvider, AgentQuery
from ..agent.registry import build_agent, installed_agents
from ..discovery.agent_search import AgentSearchReport, AgentSearchRunner, SearchLimits
from ..discovery.candidate import PipelineOutcome
from ..discovery.search_engines import KINDS, EngineBackend, EngineEntry, SearchEngineRegistry
from ..discovery.web import WebSearchBackend
from ..profile.model import Profile
from ..progress import Progress

if TYPE_CHECKING:
    from .app import App


@dataclass
class AgentRun:
    session_id: str
    report: AgentSearchReport
    outcomes: list[PipelineOutcome] = field(default_factory=list)
    proposals_queued: int = 0


class AgentService:
    def __init__(self, app: "App"):
        self.app = app
        self._agent: AgentProvider | None = None

    # ------------------------------------------------------------ configuration
    def agent(self) -> AgentProvider:
        if self._agent is None:
            self._agent = build_agent(self.app.config.values.get("agent", {}))
        return self._agent

    def agent_status(self) -> tuple[str, bool, str]:
        a = self.agent()
        ok, why = a.available()
        return a.name, ok, why

    @staticmethod
    def installed() -> list[tuple[str, bool, str]]:
        return installed_agents()

    def choices(self) -> list[dict]:
        """Selectable providers: the rule-based agent plus every known CLI tool, with install status."""
        current = str(self.app.config.get("agent", "provider", "rule_based"))
        out = [{"name": "rule_based", "installed": True, "what": "no model; queries and facts by rules, never leaves the machine",
                "current": current == "rule_based"}]
        for name, installed, what in installed_agents():
            out.append({"name": name, "installed": installed, "what": what, "current": current == name})
        return out

    def set_provider(self, name: str) -> str:
        """Select the agent provider and save it under [agent] in config.toml."""
        known = {c["name"] for c in self.choices()}
        if name not in known:
            raise ValueError(f"unknown agent provider {name!r}; choose one of {', '.join(sorted(known))}")
        self._write_agent_key("provider", f'"{name}"')
        self.app.config.values.setdefault("agent", {})["provider"] = name
        self._agent = None
        self.app.log.write("agent.provider", provider=name)
        return name

    # ------------------------------------------------------------ search engines
    def engine_registry(self) -> SearchEngineRegistry:
        names = list(self.app.config.get("agent", "search_backends", ["duckduckgo", "bing", "wikipedia"]) or [])
        keys = self.app.config.get("agent", "search_keys", {}) or {}
        return SearchEngineRegistry(self.app.paths.search_engines, names, {k: str(v) for k, v in keys.items()})

    def backends(self) -> list[WebSearchBackend]:
        """Enabled engines that are usable now (an engine without its key is left out)."""
        return [b for b in self.engine_registry().enabled() if b.available()[0]]

    def engines(self) -> list[dict]:
        reg = self.engine_registry()
        out = []
        for e in reg.list():
            ok, why = e.backend.available()
            out.append({"name": e.name, "kind": e.backend.kind, "enabled": e.enabled, "available": ok, "why": why,
                        "what": e.backend.description, "region": e.backend.region, "verified": e.backend.verified,
                        "source": e.source, "order": reg.enabled_names.index(e.name) if e.name in reg.enabled_names else None})
        out.sort(key=lambda d: (d["order"] is None, d["order"] or 0, d["name"]))
        return out

    def set_backends(self, names: list[str]) -> list[str]:
        """Choose which engines Agent Search uses, in order; saved under [agent] in config.toml."""
        reg = self.engine_registry()
        unknown = [n for n in names if n not in reg.entries]
        if unknown:
            raise ValueError("unknown search engine(s): " + ", ".join(unknown))
        self._write_agent_key("search_backends", "[" + ", ".join(f'"{n}"' for n in names) + "]")
        self.app.config.values.setdefault("agent", {})["search_backends"] = list(names)
        self.app.log.write("search.backends", names=names)
        return list(names)

    def add_engine(self, cfg: dict) -> Path:
        import re
        name = re.sub(r"[^a-z0-9_-]+", "_", str(cfg.get("name", "")).strip().lower()).strip("_")
        if not name:
            raise ValueError("a search engine needs a name")
        cfg = dict(cfg, name=name)
        EngineBackend(cfg)                        # validates kind and url
        from .catalogue_service import _to_toml
        path = self.app.paths.search_engines / f"{name}.toml"
        path.write_text(_to_toml({k: v for k, v in cfg.items() if v not in (None, "")}), encoding="utf-8")
        self.app.log.write("search.add", name=name, path=str(path))
        return path

    def remove_engine(self, name: str) -> str:
        reg = self.engine_registry()
        e = reg.get(name)
        if e is None:
            raise ValueError(f"no search engine named {name!r}")
        if e.source != "builtin":
            Path(e.source).unlink(missing_ok=True)
            msg = f"removed {e.source}"
        else:
            msg = f"built-in engine {name} cannot be deleted; it is simply not selected"
        if name in reg.enabled_names:
            self.set_backends([n for n in reg.enabled_names if n != name])
            msg += "; taken out of the enabled list"
        return msg

    def test_engine(self, name: str, query: str = "language documentation") -> list:
        e = self.engine_registry().get(name)
        if e is None:
            raise ValueError(f"no search engine named {name!r}")
        return e.backend.search(query, limit=5)

    def _write_agent_key(self, key: str, toml_value: str) -> None:
        import re
        cfg = self.app.paths.config / "config.toml"
        text = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
        line = f"{key} = {toml_value}"
        m = re.search(r"^\[agent\]\s*$", text, re.M)
        if m:
            start = m.end()
            nxt = re.search(r"^\[", text[start:], re.M)
            block = text[start: start + nxt.start()] if nxt else text[start:]
            if re.search(rf"^{key}\s*=", block, re.M):
                block = re.sub(rf"^{key}\s*=.*$", line, block, count=1, flags=re.M)
            else:
                block = "\n" + line + block
            text = text[:start] + block + (text[start + nxt.start():] if nxt else "")
        else:
            text += f"\n[agent]\n{line}\n"
        cfg.write_text(text, encoding="utf-8")

    def limits(self) -> SearchLimits:
        g = lambda k, d: self.app.config.get("agent", k, d)
        return SearchLimits(max_queries=int(g("max_queries", 16)), hits_per_query=int(g("hits_per_query", 8)),
                            max_pages=int(g("max_pages", 40)), max_depth=int(g("max_depth", 2)),
                            per_host=int(g("per_host", 6)), max_rounds=int(g("max_rounds", 2)),
                            max_files=int(g("max_files", 40)),
                            max_bytes=int(self.app.config.get("online", "max_download_mb", 500)) * 1024 * 1024,
                            timeout=int(self.app.config.get("online", "timeout", 30)))

    # ------------------------------------------------------------ run
    def runner(self, profile: Profile, backends: list[WebSearchBackend] | None = None,
               agent: AgentProvider | None = None, progress: Progress | None = None) -> AgentSearchRunner:
        return AgentSearchRunner(agent or self.agent(), backends if backends is not None else self.backends(), profile,
                                 review_at=self.app.config.review_at, confirmed_at=self.app.config.confirmed_at,
                                 limits=self.limits(), progress=progress)

    def plan(self, profile: Profile, runner: AgentSearchRunner | None = None) -> list[AgentQuery]:
        return (runner or self.runner(profile)).plan()

    def run(self, profile: Profile, runner: AgentSearchRunner, queries: list[AgentQuery],
            on_message: Callable[[str], None] | None = None,
            on_outcome: Callable[[PipelineOutcome], None] | None = None) -> AgentRun:
        col = self.app.collection_service
        sid = col.start_session(profile, "Agent Search", {"agent": runner.agent.name, "queries": [q.text for q in queries],
                                                          "backends": [b.name for b in runner.backends]})
        pipe = col.pipeline(profile, sid)
        pipe.ctx.terms = runner.terms          # learned names during the run also inform relevance scoring
        temp = self.app.paths.temp / f"agent-{sid}"
        temp.mkdir(parents=True, exist_ok=True)

        def ingest(cand):
            self.app.sessions.bump(sid, "discovered")
            return pipe.run(cand)

        try:
            outcomes = runner.run(queries, temp, ingest, on_message=on_message, on_outcome=on_outcome)
            status = "finished"
        except KeyboardInterrupt:
            outcomes = []
            status = "interrupted"
        run = AgentRun(session_id=sid, report=runner.report, outcomes=outcomes)
        rep = runner.report
        for q in rep.queries:
            self.app.sessions.event(sid, "info", f"query [{q.basis}]: {q.text}", {"why": q.rationale})
        for v in rep.visited:
            self.app.sessions.event(sid, "info", f"visited ({v.get('action')}, {v.get('score')}): {v.get('url')}", v)
        for err in rep.errors:
            self.app.sessions.event(sid, "warn", err)
        run.proposals_queued = self._queue_proposals(profile, rep, sid)
        if getattr(runner.agent, "errors", None):
            for e in runner.agent.errors[:20]:
                self.app.sessions.event(sid, "warn", f"agent: {e}")
        self.app.sessions.event(sid, "info", "agent search complete",
                                {"hits": rep.hits, "pages": rep.pages_fetched, "relevant": rep.pages_relevant,
                                 "files": rep.files_found, "learned": rep.learned})
        try:
            for f in temp.glob("*"):
                f.unlink()
            temp.rmdir()
        except OSError:
            pass
        col.finish_session(sid, status)
        return run

    def _queue_proposals(self, profile: Profile, rep: AgentSearchReport, sid: str) -> int:
        n = 0
        seen: set[str] = set()
        for f in rep.proposals:
            key = f"{f.group}.{f.field}:{str(f.value).lower()}"
            if key in seen:
                continue
            seen.add(key)
            try:
                from ..profile import schema
                schema.field_spec(f.group, f.field)
            except KeyError:
                continue
            if profile.is_known(f.group, f.field) and not isinstance(f.value, (list, dict)):
                cur = [str(c).lower() for c in profile.collected(f.group, f.field)]
                if str(f.value).lower() in cur:
                    continue
            self.app.review_service.propose_profile_field(
                profile, f.group, f.field, f.value, f.confidence, f.evidence, source_type="agent", session_id=sid,
                quote=f.quote or None)
            self.app.sessions.bump(sid, "pending_review")
            n += 1
        return n
