"""DSpace 7 repositories (Kaipuleohone at the University of Hawaiʻi, many university archives).

Search: ``/server/api/discover/search/objects?query=…``; files: item → bundles → bitstreams.
A generic university repository is the same provider with another ``base`` URL.
"""
from __future__ import annotations

from ...profile.model import Profile
from .. import http
from ..base import CatalogueProvider, CatalogueResult, DownloadableFile

_DC_TYPES = {"sound": ["audio"], "audio": ["audio"], "video": ["video"], "image": ["image"], "dataset": ["corpus"],
             "text": ["research"], "book": ["research"], "book chapter": ["research"], "article": ["research"],
             "thesis": ["research"], "dictionary": ["dictionary"], "grammar": ["grammar"]}


class DSpaceProvider(CatalogueProvider):
    name = "dspace"
    description = "a DSpace 7 repository"
    asks_by = "name"
    licence_note = "each item states its own rights (dc.rights)"

    def __init__(self, config=None):
        super().__init__(config)
        self.base = (self.config.get("base") or "https://scholarspace.manoa.hawaii.edu").rstrip("/")
        self.name = self.config.get("name", self.name)
        self.description = self.config.get("what", self.description)
        self.homepage = self.base

    def search(self, language_profile: Profile, limit: int = 25) -> list[CatalogueResult]:
        out: list[CatalogueResult] = []
        seen: set[str] = set()
        size = max(5, limit // 2)
        for sq in self.queries(language_profile, limit=int(self.config.get("max_queries", 3))):
            url = f"{self.base}/server/api/discover/search/objects?query={http.q(sq.text)}&size={size}&dsoType=item"
            try:
                data = http.get_json(url)
            except http.HttpError as exc:
                out.append(CatalogueResult(provider=self.name, kind="lookup", title=f"{self.name}: request failed",
                                           landing_url=url, description=str(exc), query=sq.text))
                continue
            objects = data.get("_embedded", {}).get("searchResult", {}).get("_embedded", {}).get("objects", [])
            for wrapper in objects:
                obj = wrapper.get("_embedded", {}).get("indexableObject", {})
                uuid = obj.get("uuid")
                if not uuid or uuid in seen or obj.get("type") not in (None, "item"):
                    continue
                seen.add(uuid)
                md = obj.get("metadata", {})

                def dc(key: str) -> list[str]:
                    return [v.get("value") for v in md.get(key, []) if v.get("value")]

                handle = obj.get("handle")
                types: list[str] = []
                for t in dc("dc.type"):
                    types.extend(_DC_TYPES.get(t.lower(), []))
                out.append(CatalogueResult(
                    provider=self.name, kind="record", title=obj.get("name") or "(untitled)",
                    landing_url=f"{self.base}/handle/{handle}" if handle else f"{self.base}/items/{uuid}",
                    description=" ".join(dc("dc.description.abstract"))[:2000] or None,
                    language=", ".join(dc("dc.language.iso") + dc("dc.language")) or None,
                    date=(dc("dc.date.issued") or [None])[0],
                    licence=(dc("dc.rights") or dc("dc.rights.uri") or [None])[0],
                    types=types,
                    identifiers={"dspace_uuid": uuid, "handle": handle or ""},
                    metadata={"creator": dc("dc.contributor.author"), "publisher": dc("dc.publisher"),
                              "subject": dc("dc.subject"), "dc_type": dc("dc.type"),
                              "citation": (dc("dc.identifier.citation") or [None])[0]},
                    query=sq.text))
                if len(out) >= limit:
                    return out
        return out

    def fetch(self, result: CatalogueResult) -> CatalogueResult:
        uuid = result.identifiers.get("dspace_uuid")
        if uuid and not result.fetched:
            try:
                bundles = http.get_json(f"{self.base}/server/api/core/items/{uuid}/bundles")
                cap = int(self.config.get("max_files_per_record", 5))
                for b in bundles.get("_embedded", {}).get("bundles", []):
                    if b.get("name") not in ("ORIGINAL", None):
                        continue
                    link = b.get("_links", {}).get("bitstreams", {}).get("href")
                    if not link:
                        continue
                    bits = http.get_json(link)
                    for bs in bits.get("_embedded", {}).get("bitstreams", [])[:cap]:
                        content = bs.get("_links", {}).get("content", {}).get("href")
                        if content:
                            result.files.append(DownloadableFile(url=content, filename=bs.get("name"),
                                                                 size=bs.get("sizeBytes")))
            except http.HttpError as exc:
                result.metadata["file_list_error"] = str(exc)
        result.fetched = True
        return result
