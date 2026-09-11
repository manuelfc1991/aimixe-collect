"""Internet Archive: advanced search JSON, then the item's file list for downloads."""
from __future__ import annotations

import re

from ...profile.model import Profile
from .. import http
from ..base import CatalogueProvider, CatalogueResult, DownloadableFile

_MEDIATYPE_TYPES = {"audio": ["audio"], "movies": ["video"], "image": ["image"], "texts": ["research"],
                    "software": ["software"], "data": ["corpus"]}
_SKIP = re.compile(r"(_files\.xml|_meta\.xml|_meta\.sqlite|\.torrent|_itemimage\.jpg|_thumb\.jpg|__ia_thumb\.jpg|_reviews\.xml)$")


class InternetArchiveProvider(CatalogueProvider):
    name = "internet_archive"
    description = "Internet Archive items: books, recordings, films, datasets"
    asks_by = "name"
    licence_note = "licence varies per item (licenseurl field); many items carry none"
    homepage = "https://archive.org"

    def search(self, language_profile: Profile, limit: int = 25) -> list[CatalogueResult]:
        out: list[CatalogueResult] = []
        seen: set[str] = set()
        rows = max(5, limit // 2)
        for sq in self.queries(language_profile, limit=int(self.config.get("max_queries", 4))):
            term = sq.text.removesuffix(" language")
            query = f'"{term}" AND (language OR linguistic OR dictionary OR grammar OR recording OR folk OR song OR story)' \
                if sq.basis in ("alternate_name", "variety") else f'"{term}" language'
            url = ("https://archive.org/advancedsearch.php?q=" + http.q(query) +
                   "&fl%5B%5D=identifier&fl%5B%5D=title&fl%5B%5D=mediatype&fl%5B%5D=description&fl%5B%5D=licenseurl"
                   "&fl%5B%5D=language&fl%5B%5D=date&fl%5B%5D=creator&fl%5B%5D=subject"
                   f"&rows={rows}&output=json")
            try:
                data = http.get_json(url)
            except http.HttpError as exc:
                out.append(CatalogueResult(provider=self.name, kind="lookup", title="internet_archive: request failed",
                                           landing_url=url, description=str(exc), query=sq.text))
                continue
            for doc in data.get("response", {}).get("docs", []):
                ident = doc.get("identifier")
                if not ident or ident in seen:
                    continue
                seen.add(ident)
                desc = doc.get("description")
                if isinstance(desc, list):
                    desc = " ".join(str(d) for d in desc)
                lang = doc.get("language")
                if isinstance(lang, list):
                    lang = ", ".join(str(x) for x in lang)
                subjects = doc.get("subject")
                out.append(CatalogueResult(
                    provider=self.name, kind="record", title=str(doc.get("title") or ident),
                    landing_url=f"https://archive.org/details/{ident}", description=str(desc)[:2000] if desc else None,
                    language=str(lang) if lang else None, date=str(doc.get("date") or "")[:10] or None,
                    licence=doc.get("licenseurl"), types=_MEDIATYPE_TYPES.get(doc.get("mediatype", ""), []),
                    identifiers={"ia_identifier": ident},
                    metadata={"mediatype": doc.get("mediatype"), "creator": doc.get("creator"),
                              "subject": subjects if isinstance(subjects, list) else ([subjects] if subjects else [])},
                    query=sq.text))
                if len(out) >= limit:
                    return out
        return out

    def fetch(self, result: CatalogueResult) -> CatalogueResult:
        ident = result.identifiers.get("ia_identifier")
        if ident and not result.fetched:
            try:
                data = http.get_json(f"https://archive.org/metadata/{ident}/files")
                files = data.get("result", []) if isinstance(data, dict) else []
                originals = [f for f in files if f.get("source") == "original" and not _SKIP.search(f.get("name", ""))]
                originals.sort(key=lambda f: int(f.get("size") or 0))
                cap = int(self.config.get("max_files_per_record", 5))
                for f in originals[:cap]:
                    result.files.append(DownloadableFile(
                        url=f"https://archive.org/download/{ident}/{http.q(f['name']).replace('+', '%20')}",
                        filename=f["name"], size=int(f["size"]) if f.get("size") else None, format=f.get("format")))
            except http.HttpError as exc:
                result.metadata["file_list_error"] = str(exc)
        result.fetched = True
        return result
