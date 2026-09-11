"""Small HTTP helper on ``urllib``: JSON/text GET with a disk cache, streamed downloads."""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

USER_AGENT = "aimixe-collect/0.1 (+language documentation collection; contact: local user)"
DEFAULT_TIMEOUT = 30
_cache_dir: Path | None = None
_cache_ttl = 6 * 3600


class HttpError(Exception):
    pass


def iri_to_uri(url: str) -> str:
    """Percent-encode non-ASCII characters (and spaces) so the request line is plain ASCII.

    Links scraped from pages are often IRIs: https://en.wikipedia.org/wiki/Tai_Lü_language.
    """
    if url.isascii() and " " not in url:
        return url
    u = urllib.parse.urlsplit(url)
    host = u.hostname.encode("idna").decode("ascii") if u.hostname and not u.hostname.isascii() else (u.hostname or "")
    netloc = host
    if u.port:
        netloc += f":{u.port}"
    if u.username:
        netloc = f"{u.username}{':' + u.password if u.password else ''}@{netloc}"
    path = urllib.parse.quote(u.path, safe="/%:@!$&'()*+,;=~-._")
    query = urllib.parse.quote(u.query, safe="=&%+/:@!$'()*,;?~-._")
    frag = urllib.parse.quote(u.fragment, safe="%/?:@!$&'()*+,;=~-._")
    return urllib.parse.urlunsplit((u.scheme, netloc, path, query, frag))


def configure_cache(directory: Path | None, ttl_seconds: int = _cache_ttl) -> None:
    global _cache_dir, _cache_ttl
    _cache_dir = directory
    _cache_ttl = ttl_seconds
    if directory:
        directory.mkdir(parents=True, exist_ok=True)


def _cache_path(url: str, accept: str) -> Path | None:
    if _cache_dir is None:
        return None
    return _cache_dir / (hashlib.sha256((accept + url).encode()).hexdigest()[:32] + ".cache")


def get_bytes(url: str, accept: str = "*/*", timeout: int = DEFAULT_TIMEOUT, use_cache: bool = True,
              headers: dict[str, str] | None = None) -> tuple[bytes, str]:
    """GET a URL. Returns (body, content_type). Cached on disk for a few hours."""
    cp = _cache_path(url, accept) if use_cache else None
    if cp and cp.exists() and time.time() - cp.stat().st_mtime < _cache_ttl:
        meta = cp.with_suffix(".type")
        return cp.read_bytes(), (meta.read_text() if meta.exists() else "")
    req = urllib.request.Request(iri_to_uri(url), headers={"User-Agent": USER_AGENT, "Accept": accept, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            ctype = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        raise HttpError(f"HTTP {exc.code} for {url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise HttpError(f"{type(exc).__name__}: {exc} for {url}") from exc
    if cp:
        cp.write_bytes(body)
        cp.with_suffix(".type").write_text(ctype)
    return body, ctype


def get_json(url: str, timeout: int = DEFAULT_TIMEOUT, use_cache: bool = True) -> Any:
    body, _ = get_bytes(url, accept="application/json", timeout=timeout, use_cache=use_cache)
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise HttpError(f"not JSON: {url}") from exc


def get_text(url: str, timeout: int = DEFAULT_TIMEOUT, use_cache: bool = True) -> str:
    body, ctype = get_bytes(url, accept="text/html,application/xhtml+xml,text/plain,*/*", timeout=timeout,
                            use_cache=use_cache)
    m = re.search(r"charset=([\w-]+)", ctype or "")
    enc = m.group(1) if m else "utf-8"
    try:
        return body.decode(enc, "replace")
    except LookupError:
        return body.decode("utf-8", "replace")


def head_status(url: str, timeout: int = 15) -> int | None:
    req = urllib.request.Request(iri_to_uri(url), method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def filename_from_response(url: str, content_disposition: str | None) -> str:
    if content_disposition:
        m = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition)
        if m:
            return urllib.parse.unquote(m.group(1)).strip('" ')
        m = re.search(r'filename="?([^";]+)"?', content_disposition)
        if m:
            return m.group(1).strip()
    path = urllib.parse.urlparse(url).path
    name = urllib.parse.unquote(path.rsplit("/", 1)[-1]) or "download"
    if name == "content" and "/files/" in path:            # Zenodo: .../files/<name>/content
        name = urllib.parse.unquote(path.split("/files/")[1].split("/")[0])
    return name


def download_file(url: str, dest_dir: Path, filename: str | None = None, max_bytes: int = 500 * 1024 * 1024,
                  timeout: int = DEFAULT_TIMEOUT, progress=None) -> Path:
    """Stream a URL into ``dest_dir``; raises HttpError when the size cap is exceeded.

    ``progress(bytes_done, total_or_None)`` is called every few megabytes.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(iri_to_uri(url), headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            length = resp.headers.get("Content-Length")
            if length and int(length) > max_bytes:
                raise HttpError(f"{url}: {int(length)} bytes exceeds the download cap")
            name = filename or filename_from_response(url, resp.headers.get("Content-Disposition"))
            name = re.sub(r"[\\/:*?\"<>|]+", "_", name)[:150] or "download"
            target = dest_dir / name
            n = 1
            while target.exists():
                target = dest_dir / f"{n}-{name}"
                n += 1
            written = 0
            total = int(length) if length else None
            next_tick = 512 * 1024
            with target.open("wb") as fh:
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    written += len(chunk)
                    if progress and written >= next_tick:
                        next_tick += 512 * 1024
                        progress(written, total)
                    if written > max_bytes:
                        fh.close()
                        target.unlink(missing_ok=True)
                        raise HttpError(f"{url}: exceeds the download cap")
                    fh.write(chunk)
            if progress:
                progress(written, total or written)
            return target
    except urllib.error.HTTPError as exc:
        raise HttpError(f"HTTP {exc.code} for {url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise HttpError(f"{type(exc).__name__}: {exc} for {url}") from exc


def q(text: str) -> str:
    return urllib.parse.quote_plus(text)
