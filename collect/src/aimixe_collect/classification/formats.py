"""File-format detection (specification §12). Unknown formats are still accepted."""
from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path

# extension -> (format, storage category)
_EXT: dict[str, tuple[str, str]] = {}


def _add(category: str, fmt_map: dict[str, str]) -> None:
    for ext, fmt in fmt_map.items():
        _EXT[ext] = (fmt, category)


_add("text", {
    "txt": "text", "md": "markdown", "rtf": "rtf", "srt": "subtitles", "vtt": "subtitles",
    "csv": "csv", "tsv": "tsv", "json": "json", "jsonl": "jsonl", "xml": "xml", "yaml": "yaml",
    "yml": "yaml", "toml": "toml", "html": "html", "htm": "html", "tex": "latex", "bib": "bibtex",
    # linguistic annotation and interchange
    "eaf": "elan", "pfsx": "elan-prefs", "textgrid": "praat-textgrid", "flextext": "flex-text",
    "fwdata": "flex-project", "fwbackup": "flex-backup", "lift": "lift", "db": "toolbox-or-sqlite",
    "sfm": "toolbox-sfm", "tbx": "toolbox", "conllu": "conll-u", "conll": "conll", "xigt": "xigt",
    "tei": "tei", "trs": "transcriber", "cha": "chat", "exb": "exmaralda", "ann": "brat",
    "ipa": "text", "lex": "lexicon-text", "dic": "dictionary-text", "aff": "hunspell",
})
_add("documents", {
    "pdf": "pdf", "doc": "msword", "docx": "docx", "odt": "odt", "ppt": "powerpoint",
    "pptx": "pptx", "odp": "odp", "xls": "excel", "xlsx": "xlsx", "ods": "ods", "epub": "epub",
    "djvu": "djvu", "ps": "postscript",
})
_add("audio", {
    "wav": "wav", "mp3": "mp3", "flac": "flac", "ogg": "ogg", "oga": "ogg", "m4a": "m4a",
    "aac": "aac", "wma": "wma", "aiff": "aiff", "aif": "aiff", "opus": "opus", "amr": "amr",
})
_add("video", {
    "mp4": "mp4", "mkv": "mkv", "mov": "quicktime", "avi": "avi", "webm": "webm", "wmv": "wmv",
    "mpg": "mpeg", "mpeg": "mpeg", "m4v": "m4v", "3gp": "3gp", "mts": "avchd",
})
_add("images", {
    "png": "png", "jpg": "jpeg", "jpeg": "jpeg", "tif": "tiff", "tiff": "tiff", "gif": "gif",
    "bmp": "bmp", "svg": "svg", "webp": "webp", "heic": "heic", "psd": "photoshop",
})
_add("archives", {
    "zip": "zip", "tar": "tar", "gz": "gzip", "tgz": "tar-gzip", "bz2": "bzip2", "xz": "xz",
    "7z": "7z", "rar": "rar", "iso": "iso-image",
})
_add("other", {
    "parquet": "parquet", "sqlite": "sqlite", "sqlite3": "sqlite", "h5": "hdf5", "hdf5": "hdf5",
    "npz": "numpy", "pkl": "pickle", "ttf": "font-truetype", "otf": "font-opentype",
    "woff": "font-woff", "woff2": "font-woff2", "kmn": "keyman-keyboard", "kmp": "keyman-package",
    "klc": "ms-keyboard-layout", "keylayout": "mac-keyboard-layout", "py": "source-python",
    "js": "source-javascript", "sh": "source-shell", "r": "source-r", "exe": "executable",
    "apk": "android-package", "jar": "java-archive",
})

_MAGIC: list[tuple[bytes, str, str]] = [
    (b"%PDF", "pdf", "documents"),
    (b"PK\x03\x04", "zip", "archives"),
    (b"\x1f\x8b", "gzip", "archives"),
    (b"7z\xbc\xaf\x27\x1c", "7z", "archives"),
    (b"Rar!", "rar", "archives"),
    (b"RIFF", "wav", "audio"),
    (b"ID3", "mp3", "audio"),
    (b"fLaC", "flac", "audio"),
    (b"OggS", "ogg", "audio"),
    (b"\x89PNG", "png", "images"),
    (b"\xff\xd8\xff", "jpeg", "images"),
    (b"GIF8", "gif", "images"),
    (b"II*\x00", "tiff", "images"),
    (b"MM\x00*", "tiff", "images"),
    (b"\x1aE\xdf\xa3", "mkv", "video"),
    (b"SQLite format 3", "sqlite", "other"),
    (b"\xd0\xcf\x11\xe0", "ms-office-legacy", "documents"),
]


@dataclass
class FormatInfo:
    format: str
    category: str
    mime: str | None
    extension: str
    detected_by: str          # extension | magic | extension+magic | unknown


def detect_format(path: Path) -> FormatInfo:
    ext = path.suffix.lower().lstrip(".")
    if path.name.lower().endswith(".tar.gz"):
        ext = "tgz"
    mime = mimetypes.guess_type(path.name)[0]
    by_ext = _EXT.get(ext)
    head = b""
    try:
        with path.open("rb") as fh:
            head = fh.read(16)
    except OSError:
        pass
    by_magic = None
    for sig, fmt, cat in _MAGIC:
        if head.startswith(sig):
            by_magic = (fmt, cat)
            break
    if by_magic and by_magic[0] == "zip" and ext in ("docx", "xlsx", "pptx", "odt", "ods", "odp", "epub", "kmp", "jar", "apk"):
        by_magic = None  # zip container with a known office/package extension: trust the extension
    if by_ext and by_magic:
        return FormatInfo(by_ext[0], by_ext[1], mime, ext, "extension+magic")
    if by_ext:
        return FormatInfo(by_ext[0], by_ext[1], mime, ext, "extension")
    if by_magic:
        return FormatInfo(by_magic[0], by_magic[1], mime, ext, "magic")
    if head and _looks_text(head):
        return FormatInfo("text", "text", mime or "text/plain", ext, "content")
    return FormatInfo("unknown", "other", mime, ext, "unknown")


def _looks_text(head: bytes) -> bool:
    if not head:
        return False
    if b"\x00" in head:
        return False
    printable = sum(1 for b in head if 32 <= b < 127 or b in (9, 10, 13) or b >= 128)
    return printable / len(head) > 0.9
