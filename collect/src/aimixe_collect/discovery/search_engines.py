"""Search engines as data (``data/search-engines.toml`` + ``~/.aimixe/search-engines/*.toml``).

One configurable backend class handles three kinds — ``json`` APIs, ``rss``/Atom feeds and
``html`` result pages — so a user anywhere can add whatever engine they can reach, with or
without an API key. See the TOML file for the field reference.
"""
from __future__ import annotations

import html as htmllib
import os
import re
import tomllib
import urllib.parse
from dataclasses import dataclass
from importlib import resources as ilr
from pathlib import Path
from typing import Any

from ..catalogues import http
from .web import WebHit, WebSearchBackend

KINDS = ("json", "rss", "html")


def _clean(s: str) -> str:
    return htmllib.unescape(re.sub(r"<[^>]+>", " ", s or "")).replace("\xa0", " ").strip()


class EngineBackend(WebSearchBackend):
    """A search engine described by a TOML table."""

    def __init__(self, cfg: dict[str, Any], key: str | None = None, cx: str | None = None):
        self.cfg = cfg
        self.name = cfg["name"]
        self.kind = cfg.get("kind", "html")
        if self.kind not in KINDS:
            raise ValueError(f"search engine {self.name!r}: kind must be one of {', '.join(KINDS)}")
        if "url" not in cfg:
            raise ValueError(f"search engine {self.name!r}: 'url' is required")
        self.key = key
        self.cx = cx
        self.description = cfg.get("what", "")
        self.region = cfg.get("region", "")
        self.verified = bool(cfg.get("verified", False))

    # ------------------------------------------------------------ availability
    def available(self) -> tuple[bool, str]:
        if self.cfg.get("needs_key") and not self.key:
            return False, (f"needs an API key: put {self.name} = \"…\" under [agent.search_keys] in config.toml "
                           f"or set AIMIXE_SEARCH_KEY_{self.name.upper()}")
        if self.cfg.get("needs_cx") and not self.cx:
            return False, f"needs an id (cx): put {self.name}_cx = \"…\" under [agent.search_keys]"
        return True, ""

    # ------------------------------------------------------------ search
    def _url(self, query: str) -> str:
        q = query.replace('"', "") if self.cfg.get("strip_quotes") else query
        return self.cfg["url"].format(q=urllib.parse.quote_plus(q), raw=q, key=self.key or "", cx=self.cx or "",
                                      lang=self.cfg.get("lang", "en"))

    def _headers(self) -> dict[str, str]:
        h = {}
        if self.cfg.get("key_header") and self.key:
            h[self.cfg["key_header"]] = self.key
        if self.kind == "html":
            h["Accept-Language"] = self.cfg.get("accept_language", "en,zh;q=0.8,*;q=0.5")
        return h

    def search(self, query: str, limit: int = 10) -> list[WebHit]:
        ok, why = self.available()
        if not ok:
            raise http.HttpError(f"{self.name}: {why}")
        url = self._url(query)
        timeout = int(self.cfg.get("timeout", 30))
        if self.kind == "json":
            body, _ = http.get_bytes(url, accept="application/json", timeout=timeout, use_cache=False, headers=self._headers())
            import json
            try:
                data = json.loads(body.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                raise http.HttpError(f"{self.name}: not JSON (blocked or wrong url?)")
            hits = self._from_json(data, query)
        else:
            body, _ = http.get_bytes(url, accept="text/html,application/xml,application/rss+xml,*/*", timeout=timeout,
                                     use_cache=False, headers=self._headers())
            text = body.decode("utf-8", "replace")
            if self.cfg.get("blocked_pattern") and re.search(self.cfg["blocked_pattern"], text, re.I) and \
                    not re.search(self.cfg.get("link_pattern", r"$^"), text, re.S | re.I):
                raise http.HttpError(f"{self.name}: bot check / verification page returned; try another engine")
            hits = self._from_rss(text, query) if self.kind == "rss" else self._from_html(text, query, url)
        seen: set[str] = set()
        out = []
        for h in hits:
            if h.url in seen or not h.url.startswith(("http://", "https://")):
                continue
            seen.add(h.url)
            out.append(h)
            if len(out) >= limit:
                break
        return out

    def _from_json(self, data: Any, query: str) -> list[WebHit]:
        from ..catalogues.configurable import path_get
        f = self.cfg.get("fields", {})
        items = path_get(data, self.cfg.get("items", "")) or []
        if isinstance(items, dict):
            items = [items]
        hits = []
        for it in items:
            if not isinstance(it, dict):
                continue
            title = str(path_get(it, f.get("title", "title")) or "")
            url = path_get(it, f["url"]) if f.get("url") else None
            if not url and self.cfg.get("url_from_title") and title:
                url = self.cfg["url_from_title"].format(lang=self.cfg.get("lang", "en"),
                                                        title=urllib.parse.quote(title.replace(" ", "_")))
            if url:
                hits.append(WebHit(url=str(url), title=_clean(title), snippet=_clean(str(path_get(it, f.get("snippet", "snippet")) or "")),
                                   backend=self.name, query=query))
        return hits

    def _from_rss(self, xml: str, query: str) -> list[WebHit]:
        item_tag = self.cfg.get("item_tag", "item|entry")
        link_tag = self.cfg.get("link_tag", "link")
        title_tag = self.cfg.get("title_tag", "title")
        snippet_tag = self.cfg.get("snippet_tag", "description|summary|content")
        hits = []
        for m in re.finditer(rf"<(?:{item_tag})\b[^>]*>(.*?)</(?:{item_tag})>", xml, re.S | re.I):
            item = m.group(1)
            link = re.search(rf"<(?:{link_tag})[^>]*?(?:href=\"([^\"]+)\"[^>]*/?>|>(.*?)</(?:{link_tag})>)", item, re.S | re.I)
            title = re.search(rf"<(?:{title_tag})[^>]*>(.*?)</(?:{title_tag})>", item, re.S | re.I)
            desc = re.search(rf"<(?:{snippet_tag})[^>]*>(.*?)</(?:{snippet_tag})>", item, re.S | re.I)
            if link:
                u = htmllib.unescape((link.group(1) or link.group(2) or "").strip())
                hits.append(WebHit(url=u, title=_clean(title.group(1)) if title else "",
                                   snippet=_clean(desc.group(1)) if desc else "", backend=self.name, query=query))
        return hits

    def _from_html(self, page: str, query: str, page_url: str) -> list[WebHit]:
        pattern = self.cfg.get("link_pattern")
        if not pattern:
            pattern = r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>'
        hits = []
        base = self.cfg.get("base") or page_url
        for m in re.finditer(pattern, page, re.S | re.I):
            raw = m.group(1)
            title = _clean(m.group(2)) if m.lastindex and m.lastindex >= 2 else ""
            url = htmllib.unescape(raw)
            if self.cfg.get("unwrap_param"):
                u = urllib.parse.urlparse(url if url.startswith("http") else "https:" + url)
                qs = urllib.parse.parse_qs(u.query)
                if self.cfg["unwrap_param"] in qs:
                    url = qs[self.cfg["unwrap_param"]][0]
            url = urllib.parse.urljoin(base, url)
            hits.append(WebHit(url=url, title=title, snippet="", backend=self.name, query=query))
        return hits


@dataclass
class EngineEntry:
    name: str
    backend: EngineBackend
    source: str          # builtin | <path>
    enabled: bool


def load_builtin() -> list[dict[str, Any]]:
    text = ilr.files("aimixe_collect.data").joinpath("search-engines.toml").read_text(encoding="utf-8")
    return tomllib.loads(text).get("engine", [])


def load_user(directory: Path) -> list[tuple[Path, dict[str, Any]]]:
    out = []
    if directory.exists():
        for f in sorted(directory.glob("*.toml")):
            try:
                data = tomllib.loads(f.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                continue
            engines = data.get("engine")
            if isinstance(engines, list):
                out.extend((f, e) for e in engines)
            elif "name" in data:
                out.append((f, data))
    return out


class SearchEngineRegistry:
    def __init__(self, user_dir: Path, enabled_names: list[str], keys: dict[str, str] | None = None):
        self.user_dir = user_dir
        self.enabled_names = list(enabled_names)
        self.keys = dict(keys or {})
        self.entries: dict[str, EngineEntry] = {}
        self.errors: list[str] = []
        self.reload()

    def _key(self, name: str, suffix: str = "") -> str | None:
        k = f"{name}{suffix}"
        return self.keys.get(k) or os.environ.get(f"AIMIXE_SEARCH_KEY_{k.upper()}")

    def _add(self, cfg: dict[str, Any], source: str) -> None:
        try:
            b = EngineBackend(cfg, key=self._key(cfg["name"]), cx=self._key(cfg["name"], "_cx"))
        except (ValueError, KeyError) as exc:
            self.errors.append(str(exc))
            return
        self.entries[b.name] = EngineEntry(b.name, b, source, enabled=b.name in self.enabled_names)

    def reload(self) -> None:
        self.entries = {}
        self.errors = []
        for cfg in load_builtin():
            self._add(cfg, "builtin")
        for path, cfg in load_user(self.user_dir):
            self._add(cfg, str(path))

    def enabled(self) -> list[EngineBackend]:
        """Enabled engines in the configured order (unknown names are skipped)."""
        return [self.entries[n].backend for n in self.enabled_names if n in self.entries]

    def list(self) -> list[EngineEntry]:
        return list(self.entries.values())

    def get(self, name: str) -> EngineEntry | None:
        return self.entries.get(name)
