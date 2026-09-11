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
from ..discovery.web import BUILTIN_BACKENDS, ConfigurableSearchBackend, WebSearchBackend
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
        import re
        cfg = self.app.paths.config / "config.toml"
        text = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
        line = f'provider = "{name}"'
        if re.search(r"^\[agent\]", text, re.M):
            block_start = re.search(r"^\[agent\]\s*$", text, re.M).end()
            block_end = re.search(r"^\[", text[block_start:], re.M)
            block = text[block_start: block_start + block_end.start()] if block_end else text[block_start:]
            if re.search(r"^provider\s*=", block, re.M):
                new_block = re.sub(r"^provider\s*=.*$", line, block, count=1, flags=re.M)
            else:
                new_block = "\n" + line + block
            text = text[:block_start] + new_block + (text[block_start + block_end.start():] if block_end else "")
        else:
            text += f"\n[agent]\n{line}\n"
        cfg.write_text(text, encoding="utf-8")
        self.app.config.values.setdefault("agent", {})["provider"] = name
        self._agent = None
        self.app.log.write("agent.provider", provider=name)
        return name

    def backends(self) -> list[WebSearchBackend]:
        names = list(self.app.config.get("agent", "search_backends", ["duckduckgo", "bing", "wikipedia"]) or [])
        out: list[WebSearchBackend] = []
        for n in names:
            cls = BUILTIN_BACKENDS.get(n)
            if cls:
                out.append(cls())
        custom = self.app.config.get("agent", "search_api")
        if isinstance(custom, dict) and custom.get("url"):
            out.append(ConfigurableSearchBackend(custom))
        return out

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
