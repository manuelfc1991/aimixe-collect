"""Text extraction for the formats the module recognises (specification §15, Phase 4).

Derived text never touches the original; it is written under ``extracted/``.
"""
from __future__ import annotations

import csv
import html
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from ..classification.formats import FormatInfo
from .pdf import extract_pdf_text

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t]+")


def extract_text(path: Path, fmt: FormatInfo, max_bytes: int = 50_000_000) -> tuple[str, dict[str, Any], list[dict] | None]:
    """Return (text, info, pages). ``info`` records how the text was obtained."""
    size = path.stat().st_size
    if size > max_bytes:
        return "", {"extractor": "none", "reason": f"larger than {max_bytes} bytes"}, None
    f = fmt.format
    try:
        if f == "pdf":
            text, info = extract_pdf_text(path, max_bytes)
            pages = None
            if "\f" in text:
                pages = [{"page": i + 1, "chars": len(p)} for i, p in enumerate(text.split("\f")) if p.strip()]
            return text, info, pages
        if f in ("docx", "pptx", "xlsx", "odt", "odp", "ods", "epub"):
            return _zip_xml_text(path, f), {"extractor": "zip-xml"}, None
        if f == "html":
            raw = _decode(path.read_bytes())
            raw = re.sub(r"<head\b.*?</head>", " ", raw, flags=re.S | re.I)
            raw = re.sub(r"<(script|style|nav|footer)\b.*?</\1>", " ", raw, flags=re.S | re.I)
            raw = re.sub(r"<(br|p|div|li|h[1-6]|tr)\b[^>]*>", "\n", raw, flags=re.I)
            return _clean(html.unescape(_TAG.sub(" ", raw))), {"extractor": "html-strip"}, None
        if f in ("elan", "flex-text", "tei", "xml", "xigt", "exmaralda", "transcriber", "lift", "toolbox", "chat"):
            return _xml_text(path, f), {"extractor": "xml-text"}, None
        if f == "praat-textgrid":
            raw = _decode(path.read_bytes())
            return _clean("\n".join(re.findall(r'text = "(.*?)"', raw))), {"extractor": "textgrid"}, None
        if f in ("json", "jsonl"):
            raw = _decode(path.read_bytes())
            try:
                obj = json.loads(raw) if f == "json" else [json.loads(l) for l in raw.splitlines() if l.strip()]
                return _clean(_json_strings(obj)), {"extractor": "json-strings"}, None
            except json.JSONDecodeError:
                return _clean(raw), {"extractor": "raw"}, None
        if f in ("csv", "tsv"):
            raw = _decode(path.read_bytes())
            rows = list(csv.reader(io.StringIO(raw), delimiter="\t" if f == "tsv" else ","))
            return _clean("\n".join(" ".join(r) for r in rows)), {"extractor": "csv", "rows": len(rows)}, None
        if fmt.category == "text" or f in ("text", "markdown", "subtitles", "latex", "bibtex", "conll-u", "conll",
                                           "toolbox-sfm", "dictionary-text", "lexicon-text", "hunspell", "rtf"):
            raw = _decode(path.read_bytes())
            if f == "rtf":
                raw = re.sub(r"\\[a-z]+-?\d* ?|[{}]", " ", raw)
            return _clean(raw), {"extractor": "raw"}, None
    except Exception as exc:  # extraction is best effort
        return "", {"extractor": "failed", "error": f"{type(exc).__name__}: {exc}"}, None
    return "", {"extractor": "none", "reason": f"no extractor for {f}"}, None


def _zip_xml_text(path: Path, f: str) -> str:
    wanted = {
        "docx": r"^word/document\.xml$", "pptx": r"^ppt/slides/slide\d+\.xml$", "xlsx": r"^xl/(sharedStrings|worksheets/sheet\d+)\.xml$",
        "odt": r"^content\.xml$", "odp": r"^content\.xml$", "ods": r"^content\.xml$", "epub": r"\.(x?html?|xml)$",
    }[f]
    parts: list[str] = []
    with zipfile.ZipFile(path) as zf:
        for name in sorted(zf.namelist()):
            if re.search(wanted, name):
                raw = zf.read(name).decode("utf-8", "replace")
                raw = re.sub(r"</(w:p|text:p|a:p|p|div|h[1-6]|li)>", "\n", raw)
                raw = re.sub(r"<w:tab/>", "\t", raw)
                parts.append(html.unescape(_TAG.sub("", raw)))
    return _clean("\n".join(parts))


def _xml_text(path: Path, f: str) -> str:
    raw = _decode(path.read_bytes())
    if f == "elan":
        vals = re.findall(r"<ANNOTATION_VALUE>(.*?)</ANNOTATION_VALUE>", raw, re.S)
        return _clean("\n".join(html.unescape(v) for v in vals))
    if f == "lift":
        vals = re.findall(r"<text>(.*?)</text>", raw, re.S)
        return _clean("\n".join(html.unescape(_TAG.sub("", v)) for v in vals))
    raw = re.sub(r"<\?xml.*?\?>", "", raw)
    raw = re.sub(r"</(item|phrase|word|u|seg|p|tier|line|entry)>", "\n", raw)
    return _clean(html.unescape(_TAG.sub(" ", raw)))


def _json_strings(obj: Any, out: list[str] | None = None) -> str:
    out = [] if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(str(k))
            _json_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _json_strings(v, out)
    elif isinstance(obj, str):
        out.append(obj)
    return "\n".join(out)


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", "replace")


def _clean(text: str) -> str:
    text = _WS.sub(" ", text.replace("\r\n", "\n").replace("\r", "\n"))
    return re.sub(r"\n\s*\n+", "\n", text).strip()
