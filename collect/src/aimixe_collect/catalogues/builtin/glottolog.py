"""Glottolog: the languoid record for an ISO code, with classification and dialect tree.

Yields one metadata record (the JSON, stored as a resource) and profile *proposals* for
family and parent grouping that reach the profile only through the review queue.
"""
from __future__ import annotations

import ast
import re

from ...profile.model import Profile
from .. import http
from ..base import CatalogueProvider, CatalogueResult, ProfileProposal


class GlottologProvider(CatalogueProvider):
    name = "glottolog"
    description = "the reference catalogue of the world's languages: classification, dialects, bibliography"
    asks_by = "code"
    needs_code = True
    licence_note = "Glottolog data is CC BY 4.0; the works it lists carry their own licences"
    homepage = "https://glottolog.org"

    def search(self, language_profile: Profile, limit: int = 25) -> list[CatalogueResult]:
        ok, _ = self.available_for(language_profile)
        if not ok:
            return []
        code = language_profile.iso639_3
        url = f"https://glottolog.org/resource/languoid/iso/{code}.json"
        try:
            data = http.get_json(url)
        except http.HttpError as exc:
            return [CatalogueResult(provider=self.name, kind="lookup", title="glottolog: request failed",
                                    landing_url=url, description=str(exc), query=code)]
        glottocode = data.get("id", "")
        classification = _parse_classification(data.get("classification"))
        dialects = re.findall(r"'([^'\[]+) \[([a-z]{4}\d{4})\]'", data.get("newick") or "")
        landing = f"https://glottolog.org/resource/languoid/id/{glottocode}" if glottocode else url
        result = CatalogueResult(
            provider=self.name, kind="record", title=f"Glottolog languoid: {data.get('name')} [{glottocode}]",
            landing_url=landing, language=code, licence="CC-BY-4.0", types=["metadata"],
            description=f"{data.get('category', '')}; classification: {' > '.join(c[0] for c in classification)}",
            identifiers={"glottocode": glottocode, "iso639_3": code},
            metadata={"glottolog_name": data.get("name"), "level": data.get("level"),
                      "latitude": data.get("latitude"), "longitude": data.get("longitude"),
                      "classification": " > ".join(c[0] for c in classification),
                      "dialects": [d[0] for d in dialects], "child_dialect_count": data.get("child_dialect_count"),
                      "raw_json": data},
            query=code)
        src = f"Glottolog {landing}"
        if classification:
            result.proposals.append(ProfileProposal("identity", "family", classification[0][0], 0.85, src))
            if len(classification) > 1:
                result.proposals.append(ProfileProposal(
                    "identity", "parent", {"value": classification[-1][0], "type": "subgroup",
                                           "glottocode": classification[-1][1]}, 0.7, src))
        if dialects:
            result.proposals.append(ProfileProposal("orthography_location", "varieties",
                                                    [d[0] for d in dialects], 0.75, src))
        if glottocode:
            result.proposals.append(ProfileProposal("identity", "notes", f"Glottocode {glottocode}", 0.9, src))
        result.files = []   # the JSON itself is stored by the search runner as a metadata resource
        return [result]

    def extract_metadata(self, result: CatalogueResult) -> dict:
        meta = super().extract_metadata(result)
        meta.pop("raw_json", None)
        return meta


def _parse_classification(raw) -> list[tuple[str, str]]:
    """The API returns the classification as a Python-literal-looking string or a list."""
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return []
    out = []
    for item in raw or []:
        if isinstance(item, dict) and item.get("name"):
            out.append((item["name"], item.get("id", "")))
    return out
