"""Resource relevance detection (specification §7): explainable 0–100 score.

Every signal contributes a weight and a reason. The profile supplies the terms: name, ISO
code, alternative names, exonyms, varieties, places, region, community names, family,
parent, scripts, known publications and translations.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..classification.resource_types import RESOURCE_TYPES
from ..language.registry import fold
from ..profile.model import Profile

BANDS = (
    (90, "very_high", "Very high confidence"),
    (70, "high", "High confidence"),
    (50, "possible", "Possible match"),
    (30, "weak", "Weak match"),
    (0, "unrelated", "Unrelated"),
)

WEIGHTS = {
    "iso_code": 70, "exact_name": 70, "alternate_name": 55, "exonym": 50, "variety": 50,
    "geographic": 15, "region": 5, "community": 25, "family": 8, "parent": 15, "script": 8,
    "metadata_language": 50, "document_contents": 30, "catalogue_classification": 20,
    "known_publication": 45, "known_translation": 40, "user_asserted": 100,
    "discovery_confidence": 0,   # scaled separately
}


def band_for(score: int) -> tuple[str, str]:
    for floor, key, label in BANDS:
        if score >= floor:
            return key, label
    return "unrelated", "Unrelated"


@dataclass
class ProfileTerms:
    """Search/match terms derived from a profile, grouped by signal."""
    iso: str | None
    name: str
    alternate_names: list[str] = field(default_factory=list)
    exonyms: list[str] = field(default_factory=list)
    varieties: list[str] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
    region: list[str] = field(default_factory=list)
    community: list[str] = field(default_factory=list)
    family: list[str] = field(default_factory=list)
    parent: list[str] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)
    publications: list[str] = field(default_factory=list)
    translations: list[str] = field(default_factory=list)
    other_languages: list[str] = field(default_factory=list)
    weak: set[str] = field(default_factory=set)       # folded names that are shared by many languages or are common words

    def all_terms(self) -> dict[str, list[str]]:
        d = {
            "alternate_name": self.alternate_names, "exonym": self.exonyms, "variety": self.varieties,
            "geographic": self.places, "region": self.region, "community": self.community, "family": self.family,
            "parent": self.parent, "script": self.scripts, "known_publication": self.publications,
            "known_translation": self.translations,
        }
        return {k: [t for t in v if t] for k, v in d.items()}


def _strs(values: list) -> list[str]:
    out: list[str] = []
    for v in values:
        if isinstance(v, dict):
            for k in ("name", "title", "value"):
                if v.get(k):
                    out.append(str(v[k]))
                    break
        elif v:
            out.append(str(v))
    return out


def terms_from_profile(profile: Profile) -> ProfileTerms:
    p = profile
    community: list[str] = []
    for v in p.collected("community_status", "community"):
        if isinstance(v, dict):
            for vals in v.values():
                community.extend(_strs(vals if isinstance(vals, list) else [vals]))
        else:
            community.append(str(v))
    region = p.display_value("orthography_location", "region")
    parent = p.display_value("identity", "parent")
    alt_names = _strs(p.collected("identity", "alternate_names"))
    weak: set[str] = set()
    try:
        from ..language.registry import load_registry
        reg = load_registry()
        for n in alt_names + _strs([parent] if parent else []):
            if fold(n) != fold(p.name) and reg.ambiguous_name(n):
                weak.add(fold(n))
    except Exception:
        pass
    for n in alt_names:
        if _common_words_only(n):
            weak.add(fold(n))
    return ProfileTerms(
        iso=p.iso639_3,
        name=p.name,
        alternate_names=alt_names,
        exonyms=_strs(p.collected("identity", "exonyms")),
        varieties=_strs(p.collected("orthography_location", "varieties")),
        places=_strs(p.collected("orthography_location", "places")),
        region=[r.strip() for r in str(region).replace("/", ",").split(",") if r.strip()] if region else [],
        community=community,
        family=[str(p.display_value("identity", "family"))] if p.is_known("identity", "family") else [],
        parent=_strs([parent]) if parent else [],
        scripts=_strs(p.collected("identity", "scripts")),
        publications=_strs(p.collected("translation_publication", "publication")),
        translations=_strs(p.collected("translation_publication", "translation")),
        other_languages=_strs(p.collected("orthography_location", "other_languages")),
        weak=weak,
    )


@dataclass
class RelevanceResult:
    score: int
    band: str
    band_label: str
    reasons: list[str]
    matched_terms: list[str]


# Ordinary English words that are also language names (Even, Bench, Gun, Male, Mono, Chin, Ache, Bench, Bata …).
# A match on such a name needs language context nearby (see _language_context) to count in full.
_ENGLISH_WORD_NAMES = set("""even bench gun male mono chin ache bata bench bit bom bore bum bun cat cha chip come dan day dog
east ewe fur gaga gay gun ha hem ho ii ipo kid koi lai lala lame law lay lo lot mam man mango me mo mom mum nap no
nut ok one pa pan pen pet poke pom pop rat rest ring roll ro ron sa sam sap saw sea she so son sun tan tap tau tea ten
tin tip to toe ton tot tu tuna ugo uma uni var way win wo yes yo you zip aka ama ari asa ata bee bel ben bi bo bua
cam can car col cul dai dam dan dao dap day dei dem den dia dim din dip doe don dom dot dua duo ela ele eli emu era ese
eve fa fan far fas fat fil fon for fun gab gal gan gap gas gen get gia gin git go gor gua gud gum gur ha hai han hao
he hi hit ho hop hot hu hui ido in io ira iru is it ja jam jen jo ju kam kan kar kas kat kaw ke kei kem ken kim kin
kit ko kol kom kon kor kot ku kui kum kur kwa la lab lac lag lak lam lap las lau le lem len lik lil lim lin lit lo
lok lom lon lor lu lua lug lui lun ma mai mak mal man mar mas mat mau me men mer mi min mo mon mor mu mua mun mut na
nai nam nan nao nda ne nen ng ni nii no nom non nu nya oa ob oc oi ok om on op or os ot pa pai pal pam pan pao par pat
pe pei pen pi po pom pu pua ra rai ram ran rao re ri ro ron ru rum sa sai sam san sao sar sat se sen ser si so som
son sou su sua sun ta tai tak tal tam tan tao tar tat te tem ten ti tin to tom ton tu tua tum tur tut u ua ui uk um
un ur us va vai van ve vi wa wai wan war we wo wu ya yai yan yao ye yi yo yu za zan zo""".split())

# Strong signs that the surrounding text is about a language (not "people", "texts", "village": too generic).
_CONTEXT = re.compile(r"\b(languages?|dialects?|speakers?|spoken|grammar|grammatical|dictionary|lexicon|wordlist|word list|"
                      r"vocabulary|phonolog\w*|phonetic\w*|orthograph\w*|linguist\w*|morpholog\w*|syntax|syntactic|"
                      r"negation|pronouns?|tonal|lexical|semantic\w*|clauses?|verbs?|nouns?|folktales?|bible translation|"
                      r"primer|literacy|glottolog|iso 639)\b", re.I)


def _ambiguous_name(term: str) -> bool:
    f = fold(term)
    return f in _ENGLISH_WORD_NAMES or (len(f) <= 3 and " " not in f)


def _language_context(text: str, term: str, window: int = 32) -> bool:
    """Does ``term`` occur, spelled as a proper noun, close to a word that says we are talking about a language?"""
    for m in re.finditer(r"\b" + re.escape(term) + r"\b", text):          # case-sensitive: "Even", not "even"
        if _CONTEXT.search(text[max(0, m.start() - window): m.end() + window]):
            return True
    return False


_COMMON = set("""a an and the of in on at to for by with from as is are was were be long short new old big small
north south east west upper lower central great little red black white green blue high low first second land river
mountain hill valley island lake sea bay point town city village people man men language""".split())


def _common_words_only(term: str) -> bool:
    words = fold(term).split()
    return bool(words) and all(w in _COMMON for w in words)


def _case_sensitive_present(text: str, term: str) -> bool:
    """For names made of ordinary words ("Long An"), the text must spell them as a proper noun."""
    return re.search(r"\b" + re.escape(term.strip()) + r"\b", text) is not None


_AUTHOR_PATTERNS = (
    r"\b{T}\s+(?:[A-Z]\.\s*){1,3}",                       # Zhuang W. Y.
    r"\b{T}\s+[A-Z]{1,3}\b(?![a-z])",                      # Zhuang WY
    r"\b{T}\s+[A-Z][a-z]+\s*(?:,|&|\band\b|\d{4})",     # Yongnan Zhao, ...
    r"(?:\b[A-Z]\.\s*){1,3}{T}\b",                       # W. Y. Zhuang
    r"\b{T}\s*(?:,|&|\band\b)\s*(?:[A-Z]\.\s*)*[A-Z][a-z]+",   # Zhuang, Owada & Wang
    r"(?:&|\band\b)\s*(?:[A-Z]\.\s*)*{T}\b",             # Zeng & Zhuang
    r"\b{T}\s+et\s+al\b",                                # Zhuang et al.
    r"\b{T}\s*,?\s+(?:1[6-9]|20)\d\d\b",                 # Zhuang 2015 (taxonomic authority)
)


def _only_author_context(text: str, term: str) -> bool:
    """True when a one-word name occurs only as a person's surname (initials, author lists, 'Name 2015')."""
    if " " in term.strip() or len(term) > 12:
        return False
    occurrences = [m for m in re.finditer(rf"\b{re.escape(term)}\b", text, re.I)]
    if not occurrences:
        return False
    for m in occurrences:
        window = text[max(0, m.start() - 24): m.end() + 24]
        if not any(re.search(p.replace("{T}", re.escape(term)), window) for p in _AUTHOR_PATTERNS):
            return False                                   # at least one plain, non-author occurrence
    return True


_NON_LINGUISTIC_TYPES = {"image", "audio", "video", "software", "archive", "metadata", "research", "unknown"}


def _linguistic_type(t: str) -> bool:
    ft = fold(t).replace(" ", "_")
    if ft in RESOURCE_TYPES:
        return ft not in _NON_LINGUISTIC_TYPES
    return any(k in fold(t) for k in ("dictionar", "grammar", "lexic", "wordlist", "corpus", "phonolog", "orthograph",
                                       "transcript", "interlinear", "translation", "field note", "language", "linguist"))


def _term_strength(term: str) -> float:
    n = len(fold(term).replace(" ", ""))
    if n <= 4:
        return 0.6
    if n == 5:
        return 0.8
    return 1.0


def _contains(blob: str, term: str) -> bool:
    ft = fold(term)
    if len(ft) < 3:
        return False
    # whole-word match; a bare substring only for long, distinctive terms ("changlang" must not match "chang")
    return f" {ft} " in f" {blob} " or (len(ft) >= 8 and ft in blob)


def score_text(terms: ProfileTerms, text: str, *, metadata_language: str | None = None,
               catalogue_types: list[str] | None = None, user_asserted: bool = False,
               discovery_confidence: float | None = None, contents: str | None = None) -> RelevanceResult:
    """Score a resource described by ``text`` (name, path, title, metadata joined)."""
    blob = fold(text)
    reasons: list[str] = []
    matched: list[str] = []
    total = 0.0

    if user_asserted:
        total += WEIGHTS["user_asserted"]
        reasons.append("user assigned this resource to the language")

    if terms.iso:
        iso = terms.iso.lower()
        tokens = set(blob.replace("_", " ").replace("-", " ").split())
        if iso in tokens or f"iso {iso}" in blob or f"{iso}." in blob:
            total += WEIGHTS["iso_code"]
            reasons.append(f"ISO code match: {terms.iso}")
            matched.append(terms.iso)

    used: set[str] = set()          # a term is evidence once, whatever signals list it
    name_hit = _contains(blob, terms.name) or (len(fold(terms.name)) < 3 and _language_context(text, terms.name))
    if name_hit:
        strength = 1.0
        if _ambiguous_name(terms.name) and not _language_context(text, terms.name):
            strength = 0.3
            reasons.append(f"name “{terms.name}” is an ordinary word and appears without language context")
        else:
            reasons.append(f"exact language name: {terms.name}")
        total += WEIGHTS["exact_name"] * strength
        matched.append(terms.name)
        used.add(fold(terms.name))

    for signal, values in terms.all_terms().items():
        hits = [t for t in values if fold(t) not in used and _contains(blob, t)
                and not (signal in ("alternate_name", "exonym", "variety", "parent") and _only_author_context(text, t))
                and not (_common_words_only(t) and not _case_sensitive_present(text, t))]
        used.update(fold(t) for t in hits)
        if hits:
            w = WEIGHTS[signal]
            # a short, generic name ("Naga", "Chang") or one shared by many languages ("Zhuang") is weak alone
            strength = max(_term_strength(t) * (0.5 if fold(t) in terms.weak else 1.0)
                           * (0.3 if _ambiguous_name(t) and not _language_context(text, t) else 1.0) for t in hits)
            if all(fold(t) in terms.weak for t in hits):
                signal_label = signal.replace("_", " ") + " (shared name, weak)"
            else:
                signal_label = signal.replace("_", " ")
            total += w * strength + (0.25 * w if len(hits) > 1 else 0)
            reasons.append(f"{signal_label} match: {', '.join(hits[:4])}")
            matched.extend(hits)

    if metadata_language:
        ml = fold(metadata_language)
        if terms.iso and ml == terms.iso.lower() or ml == fold(terms.name) or \
                any(ml == fold(a) for a in terms.alternate_names):
            total += WEIGHTS["metadata_language"]
            reasons.append(f"metadata language field: {metadata_language}")

    if contents:
        cblob = fold(contents[:200_000])
        chits = [t for t in [terms.name, *terms.alternate_names, *terms.varieties] if _contains(cblob, t)]
        if chits:
            total += WEIGHTS["document_contents"]
            reasons.append(f"document contents mention: {', '.join(chits[:4])}")
            matched.extend(chits)

    ling_types = [t for t in (catalogue_types or []) if _linguistic_type(t)]
    if ling_types:
        total += WEIGHTS["catalogue_classification"] * 0.5
        reasons.append(f"catalogue classification: {', '.join(ling_types[:3])}")

    if discovery_confidence is not None and total > 0:
        # a weak detection (e.g. a place name only) tempers the score; a strong one does not inflate it
        total *= min(1.0, 0.5 + 0.75 * max(0.0, min(1.0, discovery_confidence)))

    score = int(round(max(0.0, min(100.0, total))))
    key, label = band_for(score)
    return RelevanceResult(score=score, band=key, band_label=label, reasons=reasons,
                           matched_terms=sorted(set(matched), key=str.lower))
