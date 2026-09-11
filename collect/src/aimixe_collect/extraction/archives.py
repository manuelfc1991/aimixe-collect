"""Archive inspection (Phase 4): list members; extract them for ingestion when asked."""
from __future__ import annotations

import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Member:
    name: str
    size: int
    is_dir: bool


def inspect_archive(path: Path, fmt: str, limit: int = 5000) -> list[Member] | None:
    try:
        if fmt == "zip" or zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as zf:
                return [Member(i.filename, i.file_size, i.is_dir()) for i in zf.infolist()[:limit]]
        if fmt in ("tar", "tar-gzip", "gzip", "bzip2", "xz") and tarfile.is_tarfile(path):
            with tarfile.open(path) as tf:
                out = []
                for i, m in enumerate(tf):
                    if i >= limit:
                        break
                    out.append(Member(m.name, m.size, m.isdir()))
                return out
    except (OSError, zipfile.BadZipFile, tarfile.TarError):
        return None
    return None


def extract_members(path: Path, fmt: str, dest: Path, max_members: int = 200,
                    max_total_bytes: int = 2_000_000_000) -> list[tuple[Path, str]]:
    """Extract regular files into ``dest``; returns (extracted path, member name). Path-safe."""
    dest.mkdir(parents=True, exist_ok=True)
    out: list[tuple[Path, str]] = []
    total = 0
    if fmt == "zip" or zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                if info.is_dir() or len(out) >= max_members:
                    continue
                total += info.file_size
                if total > max_total_bytes:
                    break
                target = _safe_target(dest, info.filename)
                if target is None:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as dst:
                    dst.write(src.read())
                out.append((target, info.filename))
        return out
    if tarfile.is_tarfile(path):
        with tarfile.open(path) as tf:
            for m in tf:
                if not m.isfile() or len(out) >= max_members:
                    continue
                total += m.size
                if total > max_total_bytes:
                    break
                target = _safe_target(dest, m.name)
                if target is None:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                f = tf.extractfile(m)
                if f is None:
                    continue
                with target.open("wb") as dst:
                    dst.write(f.read())
                out.append((target, m.name))
    return out


def _safe_target(dest: Path, name: str) -> Path | None:
    clean = Path(*[p for p in Path(name).parts if p not in ("..", "/", "")])
    if not clean.parts:
        return None
    target = (dest / clean).resolve()
    if dest.resolve() not in target.parents and target != dest.resolve():
        return None
    return target
