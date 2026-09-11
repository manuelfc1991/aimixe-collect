"""Append-only JSONL logging under ``~/.aimixe/logs``."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JsonlLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **fields: Any) -> None:
        row = {"ts": now_iso(), "pid": os.getpid(), "event": event}
        row.update(fields)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass


def open_log(logs_dir: Path, name: str = "collect") -> JsonlLog:
    return JsonlLog(logs_dir / f"{name}.jsonl")
