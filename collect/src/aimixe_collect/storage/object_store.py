"""Write-once storage of original resources (specification §11, §13, §15).

Files are written to ``temp/`` first, fsynced, then atomically renamed into place and made
read-only. An original is never modified after storage.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

CHUNK = 1024 * 1024
STORAGE_MODES = ("copy", "move", "reference")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def safe_name(name: str, limit: int = 120) -> str:
    base = re.sub(r"[^\w.\- ]+", "_", name, flags=re.UNICODE).strip(" .")
    base = re.sub(r"\s+", " ", base)
    if len(base) > limit:
        stem, dot, ext = base.rpartition(".")
        if dot and len(ext) <= 12:
            base = stem[: limit - len(ext) - 1] + "." + ext
        else:
            base = base[:limit]
    return base or "file"


@dataclass
class StoredObject:
    path: Path          # where the bytes live now (original location when mode=reference)
    mode: str           # copy | move | reference
    sha256: str
    size: int


class ObjectStore:
    def __init__(self, temp_dir: Path):
        self.temp_dir = temp_dir
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def destination(self, dest_dir: Path, sha256: str, original_name: str) -> Path:
        return dest_dir / f"{sha256[:12]}-{safe_name(original_name)}"

    def store(self, src: Path, dest_dir: Path, sha256: str, mode: str = "copy") -> StoredObject:
        if mode not in STORAGE_MODES:
            raise ValueError(f"unknown storage mode {mode!r}")
        size = src.stat().st_size
        if mode == "reference":
            return StoredObject(path=src.resolve(), mode=mode, sha256=sha256, size=size)

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = self.destination(dest_dir, sha256, src.name)
        if dest.exists():
            # Same hash, same name: the bytes are already stored; never overwrite.
            if mode == "move":
                src.unlink()
            return StoredObject(path=dest, mode=mode, sha256=sha256, size=size)

        tmp = self.temp_dir / f".{sha256[:12]}-{os.getpid()}.part"
        try:
            if mode == "move":
                try:
                    os.replace(src, tmp)
                except OSError:
                    shutil.copy2(src, tmp)
                    src.unlink()
            else:
                shutil.copy2(src, tmp)
            with tmp.open("rb") as fh:
                os.fsync(fh.fileno())
            os.replace(tmp, dest)
        finally:
            if tmp.exists():
                tmp.unlink()
        try:
            dest.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        except OSError:
            pass
        return StoredObject(path=dest, mode=mode, sha256=sha256, size=size)

    def verify(self, stored: Path, sha256: str) -> bool:
        return stored.exists() and sha256_file(stored) == sha256
