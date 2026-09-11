"""Pre-fill a profile from the bundled registry with ``local_database`` provenance.

Nothing here is presented as user-confirmed. Confidence values are deliberately modest;
values below the configured threshold are shown as uncertain and re-asked.
"""
from __future__ import annotations

from ..language.registry import LanguageRecord, Registry
from .model import FieldValue, Profile

ISO = "ISO 639-3 (SIL International)"
GLOTTOLOG = "Glottolog 5.3"
CLDR = "Unicode CLDR likelySubtags"

# Glottolog agglomerated endangerment status -> transmission suggestion
_AES_TO_TRANSMISSION = {
    "not endangered": "strong",
    "threatened": "declining",
    "shifting": "declining",
    "moribund": "limited",
    "nearly extinct": "not_transmitted",
    "extinct": "not_transmitted",
}


def enrich_from_registry(profile: Profile, rec: LanguageRecord, registry: Registry) -> list[str]:
    """Add registry-known values to ``profile``. Returns the fields that were filled."""
    filled: list[str] = []

    def put(group: str, name: str, value, source: str, conf: float, note: str | None = None):
        if value in (None, "", [], {}):
            return
        profile.add(group, name, FieldValue(value=value, source_type="local_database",
                                            source=source, confidence=conf, note=note))
        filled.append(f"{group}.{name}")

    if rec.family:
        put("identity", "family", rec.family, GLOTTOLOG, 0.85,
            note=rec.classification or None)
    alts = [n for n in rec.alternative_names() if n.lower() != profile.name.lower()]
    if alts:
        put("identity", "alternate_names", alts, f"{ISO} name index; {GLOTTOLOG}", 0.8)
    if rec.macrolanguage:
        macro = registry.by_code(rec.macrolanguage)
        put("identity", "parent",
            {"value": macro.display_name if macro else rec.macrolanguage,
             "type": "macrolanguage", "code": rec.macrolanguage}, ISO, 0.9)
    if rec.likely_script:
        s = registry.script(rec.likely_script)
        put("identity", "scripts",
            [{"code": s.code if s else None, "name": s.name if s else rec.likely_script,
              "as_entered": rec.likely_script}],
            CLDR, 0.7, note="likely script; not a claim that the language is written in it")
    if rec.dialects:
        put("orthography_location", "varieties", list(rec.dialects), GLOTTOLOG, 0.75)
    region = registry.region_text(rec)
    if region:
        put("orthography_location", "region", region, GLOTTOLOG, 0.8,
            note=f"macroarea: {rec.macroarea}" if rec.macroarea else None)
    if rec.documentation:
        put("resources", "studies", {"state": "reported", "detail": f"most extensive description: {rec.documentation}"},
            GLOTTOLOG, 0.6)
    if rec.endangerment and rec.endangerment in _AES_TO_TRANSMISSION:
        put("community_status", "transmission",
            {"value": _AES_TO_TRANSMISSION[rec.endangerment], "detail": f"Glottolog AES: {rec.endangerment}"},
            GLOTTOLOG, 0.5)
    return filled
