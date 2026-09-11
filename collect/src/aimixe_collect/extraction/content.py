"""The optional content-extraction stage (specification §10, §15): derived files under ``extracted/``."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..classification.formats import FormatInfo
from ..logging_setup import now_iso
from .archives import inspect_archive
from .text import extract_text


def run_extraction(stored: Path, fmt: FormatInfo, out_dir: Path, basic_meta: dict[str, Any],
                   max_text_bytes: int) -> tuple[list[tuple[str, Path]], str, dict[str, Any]]:
    """Write text.txt / metadata.json / pages.json. Returns (outputs, text, extra metadata)."""
    outputs: list[tuple[str, Path]] = []
    extra: dict[str, Any] = {}
    text = ""
    pages = None
    info: dict[str, Any] = {}
    if fmt.category in ("text", "documents") or fmt.format in ("json", "csv", "tsv", "html"):
        text, info, pages = extract_text(stored, fmt, max_bytes=max_text_bytes)
    elif fmt.category == "archives":
        members = inspect_archive(stored, fmt.format)
        if members is not None:
            extra["archive_members"] = len(members)
            extra["archive_bytes"] = sum(m.size for m in members)
            extra["archive_listing"] = [m.name for m in members[:500]]
            info = {"extractor": "archive-listing"}
    if not text and not info and not extra:
        return outputs, text, extra
    out_dir.mkdir(parents=True, exist_ok=True)
    if text:
        tpath = out_dir / "text.txt"
        tpath.write_text(text, encoding="utf-8")
        outputs.append(("text", tpath))
        extra["text_chars"] = len(text)
        extra["text_extractor"] = info.get("extractor")
        if info.get("quality"):
            extra["text_quality"] = info["quality"]
    if pages:
        ppath = out_dir / "pages.json"
        ppath.write_text(json.dumps(pages, indent=1), encoding="utf-8")
        outputs.append(("pages", ppath))
    mpath = out_dir / "metadata.json"
    mpath.write_text(json.dumps({"original": str(stored), "format": fmt.format, "category": fmt.category,
                                 "extraction": info, "basic": basic_meta, "derived": {k: v for k, v in extra.items() if k != "archive_listing"},
                                 "archive_listing": extra.get("archive_listing"), "extracted_at": now_iso()},
                                indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    outputs.append(("metadata", mpath))
    return outputs, text, extra
