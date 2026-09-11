"""Web access for Agent Search: search backends, page fetching, link extraction, robots.

Backends implement ``search(query, limit) -> [WebHit]``. Built in: DuckDuckGo (HTML
endpoint), Bing (RSS), Wikipedia (article search), and a configurable JSON search API for
users with a key. None of this is tied to a model provider.
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


class DuckDuckGoBackend(WebSearchBackend):
    name = "duckduckgo"

    def search(self, query: str, limit: int = 10) -> list[WebHit]:
        page = http.get_text("https://html.duckduckgo.com/html/?q=" + http.q(query), use_cache=False)
        if "result__a" not in page and re.search(r"anomaly|challenge|bots? ", page, re.I):
            raise http.HttpError("duckduckgo: bot check page returned (HTTP 202); try later or rely on bing/wikipedia")
        hits: list[WebHit] = []
        for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=<a[^>]+class="result__a"|$)',
                             page, re.S):
            raw, title, rest = m.group(1), m.group(2), m.group(3)
            url = raw
            u = urllib.parse.urlparse(raw if raw.startswith("http") else "https:" + raw)
            qs = urllib.parse.parse_qs(u.query)
            if "uddg" in qs:
                url = qs["uddg"][0]
            sn = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', rest, re.S)
            hits.append(WebHit(url=html.unescape(url), title=_clean(title), snippet=_clean(sn.group(1)) if sn else "",
                               backend=self.name, query=query))
            if len(hits) >= limit:
                break
        return hits


class BingRssBackend(WebSearchBackend):
    name = "bing"

    def search(self, query: str, limit: int = 10) -> list[WebHit]:
        xml = http.get_text("https://www.bing.com/search?format=rss&q=" + http.q(query), use_cache=False)
        hits = []
        for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
            link = re.search(r"<link>(.*?)</link>", item, re.S)
            title = re.search(r"<title>(.*?)</title>", item, re.S)
            desc = re.search(r"<description>(.*?)</description>", item, re.S)
            if link:
                hits.append(WebHit(url=html.unescape(link.group(1).strip()), title=_clean(title.group(1)) if title else "",
                                   snippet=_clean(desc.group(1)) if desc else "", backend=self.name, query=query))
            if len(hits) >= limit:
                break
        return hits


class WikipediaBackend(WebSearchBackend):
    name = "wikipedia"

    def search(self, query: str, limit: int = 5) -> list[WebHit]:
        data = http.get_json("https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit="
                             f"{limit}&srsearch=" + http.q(query.replace('"', "")), use_cache=False)
        hits = []
        for s in data.get("query", {}).get("search", []):
            title = s.get("title", "")
            hits.append(WebHit(url="https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
                               title=title, snippet=_clean(s.get("snippet", "")), backend=self.name, query=query))
        return hits


class ConfigurableSearchBackend(WebSearchBackend):
    """A JSON search API from config: url template with {q}, items path, url/title/snippet paths."""

    def __init__(self, cfg: dict[str, Any]):
        from ..catalogues.configurable import path_get
        self._get = path_get
        self.cfg = cfg
        self.name = cfg.get("name", "custom_search")

    def search(self, query: str, limit: int = 10) -> list[WebHit]:
        data = http.get_json(self.cfg["url"].format(q=http.q(query)), use_cache=True)
        items = self._get(data, self.cfg.get("items", "")) or []
        f = self.cfg.get("fields", {})
        hits = []
        for it in items[:limit]:
            url = self._get(it, f.get("url", "url"))
            if url:
                hits.append(WebHit(url=str(url), title=str(self._get(it, f.get("title", "title")) or ""),
                                   snippet=str(self._get(it, f.get("snippet", "snippet")) or ""), backend=self.name, query=query))
        return hits


BUILTIN_BACKENDS: dict[str, type[WebSearchBackend]] = {
    "duckduckgo": DuckDuckGoBackend, "bing": BingRssBackend, "wikipedia": WikipediaBackend,
}


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
