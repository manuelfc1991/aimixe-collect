"""Crude, dependency-free PDF text extraction.

Good enough to find language names, titles and running text in simply encoded PDFs; CID
and custom-encoded fonts come out garbled, which is reported as low extraction quality.
When ``pdftotext`` (poppler) is on PATH it is used instead and recorded as the extractor.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import zlib
from pathlib import Path

_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
_TEXT_OPS = re.compile(rb"\[(.*?)\]\s*TJ|\((.*?)(?<!\\)\)\s*Tj", re.S)
_STR = re.compile(rb"\((.*?)(?<!\\)\)", re.S)
_ESC = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f", b"(": b"(", b")": b")", b"\\": b"\\"}


def extract_pdf_text(path: Path, max_bytes: int = 60_000_000) -> tuple[str, dict]:
    """Return (text, info). ``info['extractor']`` says how; ``info['quality']`` low|ok."""
    if shutil.which("pdftotext"):
        try:
            proc = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
                                  capture_output=True, timeout=300)
            if proc.returncode == 0 and proc.stdout.strip():
                text = proc.stdout.decode("utf-8", "replace")
                pages = text.split("\f")
                return text, {"extractor": "pdftotext", "quality": _quality(text), "pages": len([p for p in pages if p.strip()])}
        except (OSError, subprocess.TimeoutExpired):
            pass
    data = path.read_bytes()[:max_bytes]
    pages = len(re.findall(rb"/Type\s*/Page[^s]", data))
    chunks: list[str] = []
    for m in _STREAM.finditer(data):
        raw = m.group(1)
        head = data[max(0, m.start() - 400): m.start()]
        if b"/FlateDecode" in head:
            try:
                raw = zlib.decompress(raw)
            except zlib.error:
                try:
                    raw = zlib.decompressobj().decompress(raw)
                except zlib.error:
                    continue
        if b"Tj" not in raw and b"TJ" not in raw:
            continue
        chunks.append(_decode_ops(raw))
    text = "\n".join(c for c in chunks if c.strip())
    text = re.sub(r"[ \t]+", " ", text)
    return text, {"extractor": "builtin", "quality": _quality(text), "pages": pages}


def _decode_ops(raw: bytes) -> str:
    out: list[bytes] = []
    for m in _TEXT_OPS.finditer(raw):
        if m.group(1) is not None:
            parts = []
            for s in _STR.finditer(m.group(1)):
                parts.append(_unescape(s.group(1)))
            # large negative kerning in TJ arrays usually means a space
            joined = b""
            for piece, gap in zip(parts, re.findall(rb"\)\s*(-?\d+\.?\d*)", m.group(1)) + [b"0"]):
                joined += piece
                try:
                    if float(gap) < -200:
                        joined += b" "
                except ValueError:
                    pass
            out.append(joined)
        else:
            out.append(_unescape(m.group(2)))
    lines: list[str] = []
    for b in out:
        try:
            lines.append(b.decode("utf-8"))
        except UnicodeDecodeError:
            lines.append(b.decode("latin-1", "replace"))
    text = " ".join(lines)
    return re.sub(r"\s{2,}", "\n", text)


def _unescape(b: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(b):
        c = b[i:i + 1]
        if c == b"\\" and i + 1 < len(b):
            n = b[i + 1:i + 2]
            if n in _ESC:
                out += _ESC[n]
                i += 2
                continue
            if n.isdigit():
                oct_digits = re.match(rb"[0-7]{1,3}", b[i + 1:i + 4]).group(0)
                out.append(int(oct_digits, 8) & 0xFF)
                i += 1 + len(oct_digits)
                continue
            i += 1
            continue
        out += c
        i += 1
    return bytes(out)


def _quality(text: str) -> str:
    if not text.strip():
        return "empty"
    sample = text[:20000]
    letters = sum(ch.isalpha() for ch in sample)
    spaces = sample.count(" ") + sample.count("\n")
    if letters / max(1, len(sample)) < 0.4 or spaces == 0:
        return "low"
    words = re.findall(r"[A-Za-z]{3,}", sample)
    return "ok" if len(words) > 20 else "low"
