"""Providers defined by TOML, no code required (specification §4.1 custom catalogues).

Kinds:
  lookup     build a URL from the profile; nothing is fetched. ``url`` template.
  api_json   GET ``url`` (template), read JSON, map fields with dotted paths.
  html_links GET ``url`` (template), collect links matching ``link_pattern``.

Templates may use {name} {code} {query} (the current search term, URL-encoded as {q}).
Dotted paths: ``hits.hits`` selects nested keys; ``files[].links.self`` maps over a list.
"""
from __future__ import annotations

import html
import re
import urllib.parse
from typing import Any

from ..profile.model import Profile
from . import http
from .base import CatalogueProvider, CatalogueResult, DownloadableFile


def path_get(obj: Any, path: str) -> Any:
    """Dotted-path lookup: ``a.b`` nests, ``a[].b`` maps over the list at ``a``."""
    return _walk(obj, path.split(".") if path else [])


def _walk(cur: Any, parts: list[str]) -> Any:
    if not parts:
        return cur
    head, rest = parts[0], parts[1:]
    if head.endswith("[]"):
        key = head[:-2]
        if key:
            cur = cur.get(key) if isinstance(cur, dict) else None
        if cur is None:
            return None
        if not isinstance(cur, list):
            cur = [cur]
        return [_walk(item, rest) for item in cur]
    if isinstance(cur, list):
        return [_walk(item, parts) for item in cur]
    if isinstance(cur, dict):
        return _walk(cur.get(head), rest) if head in cur else None
    return None


def _first_str(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, list):
        for x in v:
            s = _first_str(x)
            if s:
                return s
        return None
    if isinstance(v, dict):
        for k in ("id", "title", "name", "value"):
            if k in v:
                return _first_str(v[k])
        return None
    return str(v)


def _strs(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        out: list[str] = []
        for x in v:
            out.extend(_strs(x))
        return out
    s = _first_str(v)
    return [s] if s else []


class ConfigurableProvider(CatalogueProvider):
    builtin = False

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.name = config["name"]
        self.kind = "lookup" if config.get("kind") == "lookup" else "record"
        self.mode = config.get("kind", "lookup")           # lookup | api_json | html_links
        self.description = config.get("what", config.get("description", ""))
        self.asks_by = config.get("asks_by", "name")
        self.needs_code = bool(config.get("needs_code", self.asks_by == "code"))
        self.licence_note = config.get("licence_note", "")
        self.homepage = config.get("homepage", "")
        self.builtin = bool(config.get("builtin", False))

    # ---------------------------------------------------------------- helpers
    def _render(self, template: str, profile: Profile, query: str) -> str:
        return template.format(name=urllib.parse.quote_plus(profile.name), code=profile.iso639_3 or "",
                               query=query, q=urllib.parse.quote_plus(query),
                               raw_name=profile.name, glottocode=self._glottocode(profile))

    @staticmethod
    def _glottocode(profile: Profile) -> str:
        for v in profile.field_values("identity", "notes", include_proposed=True):
            m = re.search(r"\b([a-z]{4}\d{4})\b", str(v.value))
            if m:
                return m.group(1)
        return ""

    # ---------------------------------------------------------------- search
    def search(self, language_profile: Profile, limit: int = 25) -> list[CatalogueResult]:
        ok, _ = self.available_for(language_profile)
        if not ok:
            return []
        if self.mode == "lookup":
            return self._lookup(language_profile)
        results: list[CatalogueResult] = []
        seen: set[str] = set()
        for sq in self.queries(language_profile, limit=int(self.config.get("max_queries", 4))):
            url = self._render(self.config["url"], language_profile, sq.text)
            try:
                if self.mode == "api_json":
                    batch = self._api_json(url, sq.text)
                elif self.mode == "html_links":
                    batch = self._html_links(url, sq.text)
                else:
                    batch = []
            except http.HttpError as exc:
                results.append(CatalogueResult(provider=self.name, kind="lookup", title=f"{self.name}: request failed",
                                               landing_url=url, description=str(exc), query=sq.text))
                continue
            for r in batch:
                if r.key in seen:
                    continue
                seen.add(r.key)
                results.append(r)
                if len(results) >= limit:
                    return results
        return results

    def _lookup(self, profile: Profile) -> list[CatalogueResult]:
        out = []
        for sq in self.queries(profile, limit=int(self.config.get("max_queries", 1))):
            url = self._render(self.config["url"], profile, sq.text)
            if self.config.get("check_exists"):
                status = http.head_status(url)
                if status is not None and status >= 400:
                    continue
            out.append(CatalogueResult(provider=self.name, kind="lookup",
                                       title=f"{self.name}: {self.description or 'look up'} — {sq.text}",
                                       landing_url=url, query=sq.text, licence=self.config.get("licence"),
                                       description=self.licence_note or None))
        return out

    def _api_json(self, url: str, query: str) -> list[CatalogueResult]:
        data = http.get_json(url, timeout=int(self.config.get("timeout", 30)))
        f = self.config.get("fields", {})
        items = path_get(data, self.config.get("items", "")) or []
        if isinstance(items, dict):
            items = [items]
        out: list[CatalogueResult] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = _first_str(path_get(item, f.get("title", "title"))) or "(untitled)"
            landing = _first_str(path_get(item, f["url"])) if f.get("url") else None
            if landing and self.config.get("url_prefix"):
                landing = self.config["url_prefix"] + landing
            files: list[DownloadableFile] = []
            if f.get("download"):
                sizes = path_get(item, f["download_size"]) if f.get("download_size") else None
                sizes = sizes if isinstance(sizes, list) else []
                for i, u in enumerate(_strs(path_get(item, f["download"]))):
                    if "://" in u:
                        size = sizes[i] if i < len(sizes) and isinstance(sizes[i], (int, float)) else None
                        files.append(DownloadableFile(url=u, size=int(size) if size else None))
            meta = {k: path_get(item, p) for k, p in self.config.get("metadata", {}).items()}
            out.append(CatalogueResult(
                provider=self.name, kind="record", title=title, landing_url=landing,
                description=_first_str(path_get(item, f["description"])) if f.get("description") else None,
                language=_first_str(path_get(item, f["language"])) if f.get("language") else None,
                date=_first_str(path_get(item, f["date"])) if f.get("date") else None,
                licence=_first_str(path_get(item, f["licence"])) if f.get("licence") else self.config.get("licence"),
                types=_strs(path_get(item, f["types"])) if f.get("types") else [],
                metadata={k: v for k, v in meta.items() if v not in (None, [], {})},
                files=files, query=query,
            ))
        return out

    def _html_links(self, url: str, query: str) -> list[CatalogueResult]:
        page = http.get_text(url, timeout=int(self.config.get("timeout", 30)))
        pattern = self.config.get("link_pattern", r".")
        out: list[CatalogueResult] = []
        seen: set[str] = set()
        for m in re.finditer(r'<a[^>]+href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', page, re.S | re.I):
            href, text = m.group(1), html.unescape(re.sub(r"<[^>]+>", " ", m.group(2))).strip()
            href = urllib.parse.urljoin(url, href)
            if href in seen or not re.search(pattern, href):
                continue
            seen.add(href)
            files = [DownloadableFile(url=href)] if re.search(self.config.get("download_pattern", r"\.(pdf|zip|wav|mp3|mp4|txt|csv|eaf|xml|docx?)$"), href, re.I) else []
            out.append(CatalogueResult(provider=self.name, kind="record", title=text[:200] or href,
                                       landing_url=href, files=files, query=query,
                                       licence=self.config.get("licence")))
        return out
