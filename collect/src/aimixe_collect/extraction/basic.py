"""Basic metadata extraction and the optional content-extraction stage.

Phase 1: filesystem facts and light format-specific metadata that need no external tools.
Phase 4 adds text extraction, archive inspection and page data under ``extracted/``.
"""
from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..classification.formats import FormatInfo


def basic_metadata(path: Path, fmt: FormatInfo) -> dict[str, Any]:
    st = path.stat()
    meta: dict[str, Any] = {
        "filename": path.name,
        "extension": fmt.extension,
        "size": st.st_size,
        "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
        "format_detected_by": fmt.detected_by,
    }
    try:
        if fmt.format == "pdf":
            meta.update(_pdf_info(path))
        elif fmt.category == "archives" and fmt.format == "zip":
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
                meta["archive_members"] = len(names)
                meta["archive_sample"] = "; ".join(names[:10])
        elif fmt.category == "text" and st.st_size < 50 * 1024 * 1024:
            meta.update(_text_info(path))
    except Exception as exc:  # metadata is best-effort; never block ingestion
        meta["metadata_error"] = f"{type(exc).__name__}: {exc}"
    return meta


def _pdf_info(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    with path.open("rb") as fh:
        head = fh.read(2_000_000)
    for key in ("Title", "Author", "Subject", "Keywords", "Creator", "Producer", "CreationDate"):
        m = re.search(rb"/" + key.encode() + rb"\s*\((.*?)\)", head, re.S)
        if m:
            try:
                out[key.lower()] = m.group(1).decode("utf-8", "replace").strip()[:500]
            except Exception:
                pass
    pages = re.findall(rb"/Type\s*/Page[^s]", head)
    if pages:
        out["pages_seen"] = len(pages)
    m = re.search(rb"/Lang\s*\((.*?)\)", head)
    if m:
        out["language"] = m.group(1).decode("ascii", "replace")
    return out


def _text_info(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()[:1_000_000]
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return {}
    lines = text.splitlines()
    out: dict[str, Any] = {"encoding": enc, "lines_sampled": len(lines)}
    if path.suffix.lower() == ".json":
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                for k in ("language", "lang", "iso", "iso639_3", "title", "name"):
                    if k in obj and isinstance(obj[k], (str, int)):
                        out[k if k != "lang" else "language"] = str(obj[k])
        except json.JSONDecodeError:
            pass
    if path.suffix.lower() == ".eaf":
        langs = set(re.findall(r'LANG_REF="([^"]+)"', text))
        if langs:
            out["language"] = ", ".join(sorted(langs))
    return out


def content_extraction(path: Path, fmt: FormatInfo, out_dir: Path) -> list[tuple[str, Path]]:
    """Optional content extraction (§10 last stage). Phase 1: no-op placeholder.

    Phase 4 writes ``text.txt``, ``metadata.json`` and ``pages.json`` under ``out_dir``.
    """
    return []
