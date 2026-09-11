"""RuleBasedAgent: query generation, analysis, classification and enrichment without a model.

It is the floor every other agent builds on: a model-backed agent adds queries and facts on
top of these, and everything here works offline.
"""
from __future__ import annotations

import re

from ..classification.classifier import classify as rule_classify
from ..classification.formats import FormatInfo
from ..language.registry import fold
from ..profile import schema
from ..profile.model import Profile
from ..relevance.scorer import ProfileTerms, score_text, terms_from_profile
from .base import (AgentProvider, AgentQuery, Analysis, AnalysisContext, Evidence, ProposedFact,
                   ResourceView)

# Query families keyed by the resources fields that switch them on (specification §2.3).
RESOURCE_QUERY_FAMILIES = {
    "recordings": ['"{name}" recordings', '"{name}" audio archive', '"{name}" documentation audio',
                   '"{name}" ELAR', '"{name}" PARADISEC'],
    "written": ['"{name}" dictionary', '"{name}" primer', '"{name}" grammar', '"{name}" wordlist'],
    "studies": ['"{name}" grammar', '"{name}" phonology', '"{name}" thesis', '"{name}" linguistic description'],
    "digital": ['"{name}" corpus', '"{name}" dataset', '"{name}" keyboard font', '"{name}" software'],
}
BASE_QUERIES = ['"{name}" language', '"{name}" dictionary', '"{name}" grammar', '"{name}" language documentation',
                '"{name}" wordlist', '"{name}" texts stories']
ISO_QUERIES = ['{iso} language "{name}"', 'ISO 639-3 {iso}']
VARIETY_QUERIES = ['"{variety}" dictionary', '"{variety}" language documentation', '"{variety}" "{name}" corpus']
ALT_QUERIES = ['"{alt}" language', '"{alt}" dictionary']
PLACE_QUERIES = ['"{name}" "{place}" language']
TRANSLATION_QUERIES = ['"{name}" Bible translation', '"{name}" New Testament']
PUBLICATION_QUERIES = ['"{title}"']

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


class RuleBasedAgent(AgentProvider):
    name = "rule_based"

    def __init__(self, max_queries: int = 24):
        self.max_queries = max_queries
        self.profile: Profile | None = None

    # ------------------------------------------------------------ queries
    def generate_search_queries(self, language_profile: Profile) -> list[AgentQuery]:
        p = language_profile
        t = terms_from_profile(p)
        out: list[AgentQuery] = []
        seen: set[str] = set()

        def add(text: str, basis: str, why: str = "") -> None:
            key = fold(text)
            if key and key not in seen and len(out) < self.max_queries:
                seen.add(key)
                out.append(AgentQuery(text, basis, why))

        for q in BASE_QUERIES:
            add(q.format(name=t.name), "name")
        if t.iso:
            for q in ISO_QUERIES:
                add(q.format(iso=t.iso, name=t.name), "code")
        # resources fields switch query families on (§2.3)
        for fld, family in RESOURCE_QUERY_FAMILIES.items():
            v = p.display_value("resources", fld)
            state = v.get("state") if isinstance(v, dict) else (str(v) if v else None)
            if state in ("yes", "limited", "reported", "historical"):
                for q in family:
                    add(q.format(name=t.name), "resources", f"profile says {fld}: {state}")
        for alt in [a for a in t.alternate_names if ", " not in a][:4]:     # skip inverted index forms "Zhuang, Yongnan"
            if len(fold(alt)) >= 5:
                for q in ALT_QUERIES:
                    add(q.format(alt=alt), "alternate_name")
        for ex in t.exonyms[:2]:
            add(f'"{ex}" language', "exonym")
        for v in t.varieties[:6]:
            for q in VARIETY_QUERIES:
                add(q.format(variety=v, name=t.name), "variety", f"{v} is a variety of {t.name}")
        for place in t.places[:3]:
            for q in PLACE_QUERIES:
                add(q.format(name=t.name, place=place), "place")
        for c in t.community[:3]:
            add(f'"{c}" "{t.name}"', "community")
        for title in t.publications[:3]:
            add(f'"{title}"', "publication")
        if t.translations:
            for q in TRANSLATION_QUERIES:
                add(q.format(name=t.name), "translation")
        return out

    # ------------------------------------------------------------ analysis
    def analyze(self, context: AnalysisContext) -> Analysis:
        terms = context.terms or terms_from_profile(context.profile)
        described = " ".join(filter(None, [context.url or "", context.title or "", context.snippet or ""]))
        rel = score_text(terms, described, contents=context.text or None,
                         metadata_language=str(context.metadata.get("language")) if context.metadata.get("language") else None)
        hints = [m for m in rel.matched_terms if fold(m) != fold(context.profile.name)]
        return Analysis(score=rel.score, reasons=rel.reasons, language_hints=hints, source="rule")

    # ------------------------------------------------------------ classification
    def classify(self, resource: ResourceView) -> list[tuple[str, float]]:
        from pathlib import Path
        fmt = FormatInfo(resource.format or "unknown", "other", None, Path(resource.name).suffix.lstrip("."), "hint")
        return [(t, c) for t, c, _ in rule_classify(Path(resource.name), resource.title, fmt, metadata=resource.metadata)]

    # ------------------------------------------------------------ enrichment
    def enrich_language_profile(self, evidence: Evidence) -> list[ProposedFact]:
        if self.profile is None:
            return extract_facts(evidence)
        t = terms_from_profile(self.profile)
        known = {n for n in [*t.alternate_names, *t.exonyms, *t.varieties] if len(fold(n)) >= 5}
        return extract_facts(evidence, profile_name=self.profile.name, known_names=known)


# ---------------------------------------------------------------- fact extraction
_NAME = r"([A-Z][\w'’-]+(?:\s[A-Z][\w'’-]+){0,2})"
PATTERNS: list[tuple[re.Pattern, str, str, float]] = [
    # "Mossang is a Tangsa variety" / "Mossang is a dialect of Tangsa"
    (re.compile(_NAME + r"\s+is\s+(?:a|an|one)\s+" + _NAME + r"\s+(?:dialect|variety|subgroup|lect|sub-tribe|subtribe)\b"),
     "orthography_location", "varieties", 0.65),
    (re.compile(_NAME + r"\s+is\s+(?:a|an|one)\s+(?:[\w-]+\s)?(?:dialect|variety|subgroup|lect|sub-tribe|subtribe)\s+of\s+(?:the\s+)?" + _NAME),
     "orthography_location", "varieties", 0.65),
    (re.compile(_NAME + r"\s+(?:dialect|variety)\s+of\s+(?:the\s+)?" + _NAME + r"\s+language"),
     "orthography_location", "varieties", 0.6),
    # "also known as X, Y and Z" / "also called X"
    (re.compile(r"(?:also\s+(?:known\s+as|called|spelled|spelt)|alternatively\s+called)\s+([^.;()]{3,80})"),
     "identity", "alternate_names", 0.55),
    # "spoken in Changlang district" / "spoken mainly in ..."
    (re.compile(r"spoken\s+(?:mainly\s+|primarily\s+|chiefly\s+)?in\s+(?:the\s+)?([A-Z][^.;,()]{2,60})"),
     "orthography_location", "places", 0.5),
    # "belongs to the Sino-Tibetan family" / "a Tibeto-Burman language"
    (re.compile(r"(?:belongs?\s+to|member\s+of|part\s+of)\s+the\s+([A-Z][\w-]+(?:\s[A-Z][\w-]+)?)\s+(?:language\s+)?family"),
     "identity", "family", 0.5),
    (re.compile(r"\ba\s+([A-Z][\w-]+(?:-[A-Z][\w-]+)?)\s+language\s+(?:spoken|of)"), "identity", "family", 0.4),
    # "written in the Latin script" / "uses the Myanmar script"
    (re.compile(r"(?:written\s+(?:in|with|using)|uses?)\s+(?:the\s+)?([A-Z][\w-]+(?:\s[A-Z][\w-]+)?)\s+(?:script|alphabet|orthography)"),
     "identity", "scripts", 0.55),
    # "approximately 8,500 speakers"
    (re.compile(r"(?:about|approximately|around|some|over|estimated)?\s*([\d,]{3,9})\s+(?:native\s+)?speakers"),
     "resources", "speakers", 0.4),
]


def extract_facts(evidence: Evidence, profile_name: str | None = None,
                  known_names: set[str] | None = None) -> list[ProposedFact]:
    """Heuristic fact extraction from prose. Low confidence by design: review decides."""
    text = re.sub(r"\s+", " ", evidence.text or "")
    out: list[ProposedFact] = []
    seen: set[str] = set()
    pname = fold(profile_name) if profile_name else None
    names_f = {fold(n) for n in (known_names or set())}
    about_it = False
    for sentence in _SENT_SPLIT.split(text)[:800]:
        fs = fold(sentence)
        names_here = (pname and pname in fs) or any(n and n in fs for n in names_f)
        pronoun_led = bool(re.match(r"\s*(it|this language|the language|its speakers)\b", sentence, re.I)) or \
            not _mentions_other_language(sentence)
        if pname and not names_here and not (pronoun_led and about_it):
            # a fact must be about this language: the sentence names it, a known alias, or follows one that did
            about_it = False
            continue
        about_it = bool(names_here) or (pronoun_led and about_it)
        for pat, group, field, conf in PATTERNS:
            for m in pat.finditer(sentence):
                value = _value_for(field, m, pname)
                if value is None:
                    continue
                key = f"{group}.{field}:{fold(str(value))}"
                if field == "speakers":
                    key = "resources.speakers"          # at most one figure per source
                if key in seen:
                    continue
                seen.add(key)
                out.append(ProposedFact(group, field, value, conf, evidence.url or evidence.title or "text",
                                        quote=sentence.strip()[:300]))
    return out


_OTHER_LANG = re.compile(r"\b[A-Z][\w-]+\s+(?:Naga|language|dialect|variety|people)\b|ISO\s*639")


def _mentions_other_language(sentence: str) -> bool:
    """A sentence that names some other language must not lend its facts to ours."""
    return bool(_OTHER_LANG.search(sentence))


_STOP = {"the", "this", "that", "these", "a", "an", "it", "he", "she", "they", "language", "languages", "north",
         "south", "east", "west", "india", "myanmar", "burma", "english", "tibeto", "naga"}


def _value_for(field: str, m: re.Match, pname: str | None):
    if field == "varieties":
        variety, parent = m.group(1), m.group(2)
        if pname and fold(parent) != pname and pname not in fold(parent):
            return None
        if fold(variety) in _STOP or (pname and fold(variety) == pname):
            return None
        return [variety]
    if field == "alternate_names":
        raw = m.group(1)
        names = [n.strip(" '\"“”") for n in re.split(r",|\bor\b|\band\b|/", raw) if n.strip(" '\"“”")]
        names = [n for n in names if 2 < len(n) < 40 and fold(n) not in _STOP and (not pname or fold(n) != pname)
                 and len(n.split()) <= 3 and n[:1].isupper()]
        return names or None
    if field == "places":
        place = m.group(1).strip()
        words = place.split()
        if not words or fold(words[0]) in _STOP:
            return None
        ptype = None
        for t in schema.PLACE_TYPES:
            if re.search(rf"\b{t}\b", place, re.I):
                ptype = t
                place = re.sub(rf"\s*\b{t}\b", "", place, flags=re.I).strip()
        return [{"name": place[:60], "type": ptype}] if place else None
    if field == "family":
        fam = m.group(1)
        return fam if fold(fam) not in _STOP else None
    if field == "scripts":
        s = m.group(1)
        return [{"name": s, "as_entered": s}] if fold(s) not in _STOP else None
    if field == "speakers":
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return m.group(1)


def terms_for(profile: Profile) -> ProfileTerms:
    return terms_from_profile(profile)
