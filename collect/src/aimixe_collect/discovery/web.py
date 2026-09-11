"""Web access for Agent Search: page fetching, link extraction, robots.

Search engines live in ``discovery/search_engines.py`` and are described by data
(``data/search-engines.toml`` plus the user's own files). ``WebSearchBackend`` is the
interface: ``search(query, limit) -> [WebHit]``.
"""
from __future__ import annotations

import html
import re
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from ..catalogues import http

DOWNLOAD_EXT = re.compile(
    r"\.(pdf|docx?|odt|rtf|txt|csv|tsv|json|xml|zip|tar|tgz|gz|7z|rar|wav|mp3|flac|ogg|m4a|mp4|mkv|webm|mov|"
    r"eaf|textgrid|flextext|lift|xlsx?|epub|djvu|png|jpe?g|tiff?|ttf|otf|kmp|kmn|sqlite|parquet)(?:$|\?)", re.I)
SKIP_HOSTS = ("facebook.com", "twitter.com", "x.com", "instagram.com", "linkedin.com", "youtube.com",
              "google.com", "accounts.", "login.", "amazon.", "pinterest.", "tiktok.com")


@dataclass
class WebHit:
    url: str
    title: str
    snippet: str = ""
    backend: str = ""
    query: str = ""


@dataclass
class Page:
    url: str
    title: str = ""
    text: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)     # (absolute url, anchor text)
    meta: dict[str, str] = field(default_factory=dict)
    content_type: str = ""
    is_file: bool = False                                          # a downloadable file, not a page


# ---------------------------------------------------------------- backends
class WebSearchBackend:
    name = "backend"

    def search(self, query: str, limit: int = 10) -> list[WebHit]:
        raise NotImplementedError


def builtin_backend(name: str) -> WebSearchBackend:
    """A built-in engine by name (duckduckgo, bing, wikipedia …), from data/search-engines.toml."""
    from .search_engines import EngineBackend, load_builtin
    for cfg in load_builtin():
        if cfg["name"] == name:
            return EngineBackend(cfg)
    raise KeyError(name)


class DuckDuckGoBackend(WebSearchBackend):
    def __init__(self) -> None:
        self._b = builtin_backend("duckduckgo")
        self.name = self._b.name

    def search(self, query: str, limit: int = 10) -> list[WebHit]:
        return self._b.search(query, limit)


class BingRssBackend(DuckDuckGoBackend):
    def __init__(self) -> None:
        self._b = builtin_backend("bing")
        self.name = self._b.name


class WikipediaBackend(DuckDuckGoBackend):
    def __init__(self) -> None:
        self._b = builtin_backend("wikipedia")
        self.name = self._b.name


# ---------------------------------------------------------------- pages
class _TextExtractor(HTMLParser):
    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.title = ""
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.meta: dict[str, str] = {}
        self._skip = 0
        self._in_title = False
        self._href: str | None = None
        self._anchor: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "noscript", "svg", "nav", "footer"):
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            if name and a.get("content"):
                self.meta[name] = a["content"][:500]
        elif tag == "a" and a.get("href"):
            self._href = urllib.parse.urljoin(self.base, a["href"].strip())
            self._anchor = []
        elif tag in ("p", "br", "li", "h1", "h2", "h3", "h4", "tr", "div", "td"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg", "nav", "footer"):
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag == "a" and self._href:
            self.links.append((self._href, " ".join(self._anchor).strip()[:200]))
            self._href = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._skip:
            return
        if self._href is not None:
            self._anchor.append(data)
        self.parts.append(data)


_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def allowed_by_robots(url: str) -> bool:
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https"):
        return True
    host = f"{u.scheme}://{u.netloc}"
    if host not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            body, _ = http.get_bytes(host + "/robots.txt", accept="text/plain", timeout=10)
            rp.parse(body.decode("utf-8", "replace").splitlines())
            _robots[host] = rp
        except http.HttpError:
            _robots[host] = None
    rp = _robots[host]
    return True if rp is None else rp.can_fetch(http.USER_AGENT, url)


def normalise_url(url: str) -> str:
    u = urllib.parse.urlparse(url.strip())
    qs = [(k, v) for k, v in urllib.parse.parse_qsl(u.query) if not k.startswith(("utm_", "fbclid", "ref"))]
    path = re.sub(r"/+$", "", u.path) or "/"
    return urllib.parse.urlunparse((u.scheme.lower(), u.netloc.lower(), path, "", urllib.parse.urlencode(qs), ""))


def looks_like_file(url: str) -> bool:
    return bool(DOWNLOAD_EXT.search(urllib.parse.urlparse(url).path + ("?" + urllib.parse.urlparse(url).query if urllib.parse.urlparse(url).query else "")))


def skip_host(url: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower()
    return any(s in host for s in SKIP_HOSTS)


def fetch_page(url: str, max_text: int = 200_000, timeout: int = 30) -> Page:
    """Fetch a URL; HTML becomes text + links, anything else is flagged as a file."""
    body, ctype = http.get_bytes(url, accept="text/html,application/xhtml+xml,*/*", timeout=timeout, use_cache=True)
    ctype = (ctype or "").lower()
    if "html" not in ctype and "xml" not in ctype and not body[:200].lower().lstrip().startswith((b"<!doctype", b"<html")):
        return Page(url=url, content_type=ctype, is_file=True)
    m = re.search(r"charset=([\w-]+)", ctype)
    try:
        text = body.decode(m.group(1) if m else "utf-8", "replace")
    except LookupError:
        text = body.decode("utf-8", "replace")
    ex = _TextExtractor(url)
    try:
        ex.feed(text)
    except Exception:
        pass
    flat = re.sub(r"[ \t]+", " ", "".join(ex.parts))
    flat = re.sub(r"\n\s*\n+", "\n", flat).strip()[:max_text]
    return Page(url=url, title=_clean(ex.title)[:300], text=flat, links=ex.links, meta=ex.meta, content_type=ctype)


def _clean(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).replace("\xa0", " ").strip()
