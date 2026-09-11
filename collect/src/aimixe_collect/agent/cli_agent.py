"""CliAgent: any command-line model tool that takes a prompt and prints an answer.

Configured in ``data/agents.toml`` (or ``[agent.cli]`` in config.toml): a ``command`` with
``{prompt}``. The tool answers in JSON; the last JSON object/array in its output is used.
Nothing here depends on a vendor: Claude, OpenAI Codex, Gemini, Qwen, Ollama, llm ... are
all just commands. Every answer is combined with the rule-based baseline, so a failing or
absent tool degrades to RuleBasedAgent instead of breaking the run.
"""
from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import tomllib
from importlib import resources as ilr
from typing import Any

from ..profile.model import Profile
from .base import (AgentProvider, AgentQuery, Analysis, AnalysisContext, Evidence, ProposedFact,
                   ResourceView)
from .rule_based import RuleBasedAgent

_JSON_RE = re.compile(r"(\{.*\}|\[.*\])", re.S)
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def load_agent_configs() -> dict[str, dict[str, Any]]:
    text = ilr.files("aimixe_collect.data").joinpath("agents.toml").read_text(encoding="utf-8")
    return {a["name"]: a for a in tomllib.loads(text).get("agent", [])}


def extract_json(text: str) -> Any:
    """The last decodable JSON object or array in free-form output (tools chat around it)."""
    text = _ANSI.sub("", text or "")
    fence = re.findall(r"```(?:json)?\s*(.*?)```", text, re.S)
    candidates = fence[::-1] + [text]
    for c in candidates:
        m = _JSON_RE.search(c)
        if not m:
            continue
        blob = m.group(1)
        # shrink from the end until it parses
        for end in range(len(blob), 0, -1):
            if blob[end - 1] not in "}]":
                continue
            try:
                return json.loads(blob[:end])
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON in agent output")


class CliAgent(AgentProvider):
    def __init__(self, config: dict[str, Any], baseline: RuleBasedAgent | None = None):
        self.name = config.get("name", "cli")
        self.command = config["command"]
        self.timeout = int(config.get("timeout", 180))
        self.max_prompt_chars = int(config.get("max_prompt_chars", 12000))
        self.baseline = baseline or RuleBasedAgent()
        self.errors: list[str] = []

    # ------------------------------------------------------------ plumbing
    def bind(self, profile: Profile) -> None:
        self.profile = profile
        self.baseline.bind(profile)

    def available(self) -> tuple[bool, str]:
        exe = shlex.split(self.command)[0]
        if shutil.which(exe) is None:
            return False, f"{exe!r} is not on PATH"
        return True, ""

    def ask(self, prompt: str) -> Any:
        prompt = prompt[: self.max_prompt_chars]
        argv = [a.replace("{prompt}", prompt) for a in shlex.split(self.command)]
        stdin = None
        if "{prompt}" not in self.command:
            stdin = prompt
        try:
            proc = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=self.timeout,
                                  encoding="utf-8", errors="replace")
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"{self.name}: {type(exc).__name__}: {exc}") from exc
        if proc.returncode != 0 and not proc.stdout.strip():
            raise RuntimeError(f"{self.name}: exit {proc.returncode}: {proc.stderr.strip()[:300]}")
        return extract_json(proc.stdout)

    def _try(self, prompt: str) -> Any | None:
        try:
            return self.ask(prompt)
        except (RuntimeError, ValueError) as exc:
            self.errors.append(str(exc))
            return None

    # ------------------------------------------------------------ interface
    def generate_search_queries(self, language_profile: Profile) -> list[AgentQuery]:
        base = self.baseline.generate_search_queries(language_profile)
        profile_json = json.dumps(language_profile.to_json(), ensure_ascii=False)[:6000]
        prompt = (
            "You help find language-documentation resources. Given this language profile (JSON), "
            "propose up to 12 additional web search queries that could find dictionaries, grammars, "
            "wordlists, corpora, recordings, theses, archives or software for THIS language or its varieties. "
            "Use alternative names, varieties, places, community names and known publications. "
            'Answer ONLY with a JSON array of objects: [{"query": "...", "basis": "...", "why": "..."}].\n\n'
            f"Profile: {profile_json}"
        )
        data = self._try(prompt)
        seen = {q.text.lower() for q in base}
        if isinstance(data, list):
            for item in data[:12]:
                if isinstance(item, dict) and item.get("query") and str(item["query"]).lower() not in seen:
                    seen.add(str(item["query"]).lower())
                    base.append(AgentQuery(str(item["query"])[:200], f"agent:{item.get('basis', '?')}",
                                           str(item.get("why", ""))[:200]))
        return base

    def analyze(self, context: AnalysisContext) -> Analysis:
        rule = self.baseline.analyze(context)
        prompt = (
            f"Does the following web page or document relate to the language '{context.profile.name}'"
            f"{' (ISO 639-3 ' + context.profile.iso639_3 + ')' if context.profile.iso639_3 else ''} "
            "or one of its varieties? Consider the title, URL and text. "
            'Answer ONLY with JSON: {"score": 0-100, "reasons": ["..."], "language_hints": ["names/varieties mentioned"], '
            '"resource_types": ["dictionary|grammar|wordlist|corpus|audio|video|research|..."]}.\n\n'
            f"URL: {context.url}\nTitle: {context.title}\nText: {context.text[:6000]}"
        )
        data = self._try(prompt)
        if isinstance(data, dict) and isinstance(data.get("score"), (int, float)):
            agent_score = int(max(0, min(100, data["score"])))
            # bounded adjustment: the agent may move the rule score by at most 25 points
            score = int(max(0, min(100, rule.score + max(-25, min(25, agent_score - rule.score)))))
            return Analysis(score=score, reasons=rule.reasons + [f"{self.name}: {r}" for r in data.get("reasons", [])[:4]],
                            language_hints=list(dict.fromkeys(rule.language_hints + [str(h) for h in data.get("language_hints", [])[:8]])),
                            resource_types=[str(t) for t in data.get("resource_types", [])[:5]], source=self.name)
        return rule

    def classify(self, resource: ResourceView) -> list[tuple[str, float]]:
        rule = self.baseline.classify(resource)
        prompt = (
            "Classify this language resource. Types: dictionary, lexicon, wordlist, corpus, grammar, phonology, "
            "morphology, syntax, orthography, translation, parallel_text, transcription, interlinear_text, audio, "
            "video, image, field_notes, research, metadata, software, archive, unknown. "
            'Answer ONLY with JSON: [{"type": "...", "confidence": 0.0-1.0}].\n\n'
            f"Name: {resource.name}\nTitle: {resource.title}\nFormat: {resource.format}\n"
            f"Metadata: {json.dumps(resource.metadata, default=str)[:1500]}\nText sample: {resource.text_sample[:2500]}"
        )
        data = self._try(prompt)
        if isinstance(data, list):
            for item in data[:5]:
                if isinstance(item, dict) and item.get("type"):
                    rule.append((str(item["type"]), float(item.get("confidence", 0.5))))
        return rule

    def enrich_language_profile(self, evidence: Evidence) -> list[ProposedFact]:
        facts = self.baseline.enrich_language_profile(evidence)
        prompt = (
            "From the text below, extract facts about the language it discusses that fit these profile fields: "
            "identity.family, identity.alternate_names (list), identity.exonyms (list), identity.parent, identity.scripts (list), "
            "orthography_location.varieties (list), orthography_location.region, orthography_location.places (list of {name,type,region,country}), "
            "orthography_location.other_languages (list), resources.speakers (number), community_status.transmission, "
            "translation_publication.translation (list), translation_publication.publication (list). "
            "Only include facts the text states; quote the supporting sentence. "
            'Answer ONLY with a JSON array: [{"group": "...", "field": "...", "value": ..., "confidence": 0.0-1.0, "quote": "..."}].\n\n'
            f"Source: {evidence.url or evidence.title}\nText: {evidence.text[:7000]}"
        )
        data = self._try(prompt)
        if isinstance(data, list):
            for item in data[:20]:
                if isinstance(item, dict) and item.get("group") and item.get("field") and "value" in item:
                    facts.append(ProposedFact(str(item["group"]), str(item["field"]), item["value"],
                                              float(item.get("confidence", 0.5)), evidence.url or evidence.title or "agent",
                                              quote=str(item.get("quote", ""))[:300], source=self.name))
        return facts
