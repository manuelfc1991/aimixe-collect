"""Language-profile field schema and question groups (specification §2.1–§2.7).

This table is data. The CLI renders prompts from it; a future UI renders forms from it.
Adding a field here needs no database migration (values are stored as rows).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Value kinds -------------------------------------------------------------------------
# text        one free-text value
# list        several free-text values (comma / semicolon separated on input)
# state       one of the availability states plus optional free-text detail
# speakers    integer, approximate ("~8500") or range ("8000-9000")
# places      list of {name, type, region, country}
# tagged_list list of free-text values, each with an optional role/type tag
# parent      {value, type}
# scripts     list of script names/codes, normalised to {code, name, as_entered}
# choice      one of the suggested values, or free text
# basis       {type, year, source}
# age_spread  {children, young_adults, adults, elderly} each yes/no/unknown + note
# entries     list of {kind, title, date, organisation, url, note}
# community   structured free text with optional sub-lists

AVAILABILITY_STATES = ("yes", "no", "unknown", "limited", "reported", "historical")

ORTHOGRAPHY_STATUS = (
    "standardized", "partially_standardized", "community_orthography", "experimental",
    "multiple_orthographies", "unwritten", "unknown",
)
SPEAKERS_BASIS_TYPES = (
    "census", "academic study", "community estimate", "government report", "fieldwork",
    "Ethnologue", "Glottolog", "unknown",
)
TRANSMISSION = ("strong", "ongoing", "declining", "limited", "not_transmitted", "unknown")
DISPLACED = ("yes", "no", "partial", "historical", "unknown")
USE_DOMAINS = (
    "home", "community", "education", "religion", "ceremonies", "media", "government",
    "market", "workplace", "literature", "digital communication",
)
OTHER_LANGUAGE_ROLES = (
    "lingua franca", "regional", "national", "neighbouring", "education", "religion", "trade",
)
PARENT_TYPES = ("parent language", "dialect group", "macrolanguage", "subgroup",
                "broader linguistic grouping")
PLACE_TYPES = ("village", "town", "city", "district", "state", "province", "region", "country")
TRANSLATION_KINDS = (
    "Bible translation", "religious translation", "government translation",
    "educational translation", "translated literature", "health materials", "dictionary",
    "translated website", "subtitles", "parallel text",
)
PUBLICATION_KINDS = (
    "book", "primer", "textbook", "newspaper", "magazine", "community publication",
    "academic publication", "dictionary", "grammar book",
)
COMMUNITY_ASPECTS = (
    "community names", "self-identification", "organizations", "language committees",
    "cultural organizations", "educational initiatives", "documentation initiatives",
    "relevant institutions",
)


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    prompt: str
    kind: str
    help: str = ""
    suggested: tuple[str, ...] = ()
    multi: bool = False
    # discovery signals this field feeds: query | relevance | offline | classify
    feeds: tuple[str, ...] = ()


@dataclass(frozen=True)
class GroupSpec:
    name: str
    title: str            # "Language Profile – <title>"
    progress_label: str   # label in the progress display
    fields: tuple[FieldSpec, ...] = field(default_factory=tuple)


GROUPS: tuple[GroupSpec, ...] = (
    GroupSpec(
        name="identity", title="Names and Classification", progress_label="Names and classification",
        fields=(
            FieldSpec("family", "Family", "Language family:", "text",
                      help="e.g. Sino-Tibetan, Austronesian", feeds=("query", "relevance")),
            FieldSpec("alternate_names", "Alternative names", "Alternative names:", "list",
                      help="Separate several names with commas", multi=True,
                      feeds=("query", "relevance", "offline")),
            FieldSpec("exonyms", "Exonyms", "Exonyms / names used by outsiders:", "list",
                      multi=True, feeds=("query", "relevance", "offline")),
            FieldSpec("parent", "Parent language/group", "Parent language/group, if applicable:",
                      "parent", help="May be a parent language, dialect group, macrolanguage, "
                      "subgroup or broader grouping. Leave blank if not known.",
                      suggested=PARENT_TYPES, feeds=("query", "relevance")),
            FieldSpec("scripts", "Scripts", "Scripts used:", "scripts", multi=True,
                      help="Script names or ISO 15924 codes, e.g. Latin, Myanmar, Deva",
                      feeds=("query", "relevance", "classify")),
            FieldSpec("notes", "Notes", "Additional notes:", "text"),
        ),
    ),
    GroupSpec(
        name="orthography_location", title="Orthography and Location",
        progress_label="Location and varieties",
        fields=(
            FieldSpec("orthography_status", "Orthography status", "Orthography status:", "choice",
                      suggested=ORTHOGRAPHY_STATUS,
                      help="Pick a value or describe it in your own words", feeds=("classify",)),
            FieldSpec("literacy", "Literacy", "Literacy information:", "text"),
            FieldSpec("varieties", "Varieties", "Known dialects / varieties:", "list", multi=True,
                      feeds=("query", "relevance", "offline")),
            FieldSpec("region", "Region", "Primary region:", "text", feeds=("query", "relevance")),
            FieldSpec("places", "Places", "Specific places where the language is spoken:", "places",
                      multi=True, help="One place per entry: name, type (village/district/...), "
                      "region, country", suggested=PLACE_TYPES,
                      feeds=("query", "relevance", "offline")),
            FieldSpec("other_languages", "Other languages", "Other languages commonly used by the "
                      "community:", "tagged_list", multi=True, suggested=OTHER_LANGUAGE_ROLES,
                      help="Lingua francas, regional/national languages, neighbouring languages, "
                      "languages of education, religion or trade", feeds=("relevance",)),
        ),
    ),
    GroupSpec(
        name="resources", title="Existing Resources", progress_label="Resources",
        fields=(
            FieldSpec("summary", "Resource summary", "Are any language resources already known?",
                      "text", feeds=("query",)),
            FieldSpec("written", "Written materials", "Are written materials available?", "state",
                      suggested=AVAILABILITY_STATES, feeds=("query",)),
            FieldSpec("recordings", "Recordings", "Are audio/video recordings available?", "state",
                      suggested=AVAILABILITY_STATES, feeds=("query",)),
            FieldSpec("studies", "Linguistic studies", "Are linguistic studies available?", "state",
                      suggested=AVAILABILITY_STATES, feeds=("query",)),
            FieldSpec("digital", "Digital resources", "Are digital resources available?", "state",
                      suggested=AVAILABILITY_STATES, feeds=("query",)),
            FieldSpec("speakers", "Speaker estimate", "Estimated number of speakers:", "speakers",
                      help="A number, an approximation (~8500) or a range (8000-9000)"),
        ),
    ),
    GroupSpec(
        name="community_status", title="Speaker and Community Information",
        progress_label="Community",
        fields=(
            FieldSpec("speakers_basis", "Speaker estimate basis",
                      "What is the basis of the speaker estimate?", "basis",
                      suggested=SPEAKERS_BASIS_TYPES, help="Type, year and source of the estimate"),
            FieldSpec("transmission", "Transmission", "Is the language being transmitted to children?",
                      "choice", suggested=TRANSMISSION),
            FieldSpec("age_spread", "Age spread", "Which age groups currently speak the language?",
                      "age_spread"),
            FieldSpec("used", "Domains of use", "Where/domains is the language actively used?",
                      "list", multi=True, suggested=USE_DOMAINS, feeds=("query",)),
            FieldSpec("displaced", "Displacement", "Has the community or language population been "
                      "displaced?", "choice", suggested=DISPLACED, feeds=("query",)),
            FieldSpec("community", "Community information", "Additional community information:",
                      "community", suggested=COMMUNITY_ASPECTS, multi=True,
                      feeds=("query", "relevance", "offline")),
        ),
    ),
    GroupSpec(
        name="translation_publication", title="Translation and Publication",
        progress_label="Translation and publication",
        fields=(
            FieldSpec("translation", "Translations", "Are translations available in this language?",
                      "entries", multi=True, suggested=TRANSLATION_KINDS,
                      feeds=("query", "relevance", "offline")),
            FieldSpec("publication", "Publications", "Are published materials available?",
                      "entries", multi=True, suggested=PUBLICATION_KINDS,
                      feeds=("query", "relevance", "offline")),
        ),
    ),
)

GROUP_BY_NAME: dict[str, GroupSpec] = {g.name: g for g in GROUPS}


def field_spec(group: str, name: str) -> FieldSpec:
    for f in GROUP_BY_NAME[group].fields:
        if f.name == name:
            return f
    raise KeyError(f"{group}.{name}")


def all_fields() -> list[tuple[GroupSpec, FieldSpec]]:
    return [(g, f) for g in GROUPS for f in g.fields]


def fields_feeding(signal: str) -> list[tuple[str, str]]:
    return [(g.name, f.name) for g, f in all_fields() if signal in f.feeds]
