"""Agent provider interface (specification §20). Provider-independent.

    class AgentProvider:
        def analyze(self, context): ...
        def classify(self, resource): ...
        def generate_search_queries(self, language_profile): ...
        def enrich_language_profile(self, evidence): ...

Implementations: RuleBasedAgent (no model, always available), CliAgent (any command-line
model tool, configured in data/agents.toml). Future ClaudeAgent / OpenAIAgent / QwenAgent /
LocalAgent classes implement the same four methods. Agents only ever *propose*.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..profile.model import Profile


@dataclass
class AgentQuery:
    text: str
    basis: str                  # name | code | alternate_name | exonym | variety | place | resources | ... | agent | learned
    rationale: str = ""


@dataclass
class AnalysisContext:
    """What the agent sees when asked whether a page or file relates to the language."""
    profile: Profile
    url: str | None
    title: str | None
    text: str                   # page text or file description (bounded)
    snippet: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    terms: Any = None           # optional ProfileTerms (profile + names learned this session)


@dataclass
class Analysis:
    score: int                  # 0–100 relevance estimate
    reasons: list[str] = field(default_factory=list)
    language_hints: list[str] = field(default_factory=list)   # names/varieties the text seems to be about
    resource_types: list[str] = field(default_factory=list)
    source: str = "rule"        # rule | <agent name>


@dataclass
class Evidence:
    text: str
    url: str | None = None
    title: str | None = None


@dataclass
class ProposedFact:
    group: str
    field: str
    value: Any
    confidence: float
    evidence: str               # where it came from (URL / file)
    quote: str = ""             # the sentence that supports it
    source: str = "rule"


@dataclass
class ResourceView:
    """What ``classify`` receives: a path or URL plus whatever is known about it."""
    name: str
    url: str | None = None
    format: str | None = None
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    text_sample: str = ""


class AgentProvider:
    name: str = "agent"

    def bind(self, profile: Profile) -> None:
        """Tell the agent which language profile the session is about (used by enrichment)."""
        self.profile = profile

    def available(self) -> tuple[bool, str]:
        return True, ""

    def analyze(self, context: AnalysisContext) -> Analysis:
        raise NotImplementedError

    def classify(self, resource: ResourceView) -> list[tuple[str, float]]:
        raise NotImplementedError

    def generate_search_queries(self, language_profile: Profile) -> list[AgentQuery]:
        raise NotImplementedError

    def enrich_language_profile(self, evidence: Evidence) -> list[ProposedFact]:
        raise NotImplementedError
