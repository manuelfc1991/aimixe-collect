"""Progress events for long runs (downloads, scans, imports), independent of the interface.

Producers call ``Progress.start/update/done`` and ``Progress.step``; the CLI renders a
status line, the web UI shows the same numbers. Speed and ETA are computed here once.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Transfer:
    key: str
    name: str
    total: int | None
    started: float = field(default_factory=time.time)
    done: int = 0
    last_emit: float = 0.0
    _samples: list[tuple[float, int]] = field(default_factory=list)

    def speed(self) -> float:
        """Bytes per second over the last few seconds."""
        now = time.time()
        self._samples.append((now, self.done))
        self._samples = [(t, b) for t, b in self._samples if now - t <= 5.0] or self._samples[-1:]
        t0, b0 = self._samples[0]
        return (self.done - b0) / (now - t0) if now - t0 > 0.2 else (self.done / max(now - self.started, 0.2))

    def eta(self) -> float | None:
        if not self.total:
            return None
        s = self.speed()
        return (self.total - self.done) / s if s > 0 else None

    def percent(self) -> float | None:
        return 100.0 * self.done / self.total if self.total else None


class Progress:
    """Thread-safe progress hub. ``emit(event: dict)`` receives every change."""

    def __init__(self, emit: Callable[[dict[str, Any]], None] | None = None, min_interval: float = 0.4):
        self.emit = emit or (lambda e: None)
        self.min_interval = min_interval
        self.active: dict[str, Transfer] = {}
        self.lock = threading.Lock()
        self.counters: dict[str, Any] = {}

    # ---------------------------------------------------------------- transfers
    def start(self, key: str, name: str, total: int | None) -> Transfer:
        with self.lock:
            t = Transfer(key, name, total)
            self.active[key] = t
        self.emit({"kind": "start", "key": key, "name": name, "total": total, **self._snapshot()})
        return t

    def update(self, key: str, done: int, total: int | None = None) -> None:
        with self.lock:
            t = self.active.get(key)
            if t is None:
                return
            t.done = done
            if total:
                t.total = total
            now = time.time()
            if now - t.last_emit < self.min_interval and (not t.total or done < t.total):
                return
            t.last_emit = now
            ev = {"kind": "progress", "key": key, "name": t.name, "done": done, "total": t.total,
                  "percent": t.percent(), "speed": t.speed(), "eta": t.eta(), **self._snapshot()}
        self.emit(ev)

    def done(self, key: str, ok: bool = True, message: str = "") -> None:
        with self.lock:
            t = self.active.pop(key, None)
        if t is None:
            return
        elapsed = time.time() - t.started
        self.emit({"kind": "done", "key": key, "name": t.name, "ok": ok, "bytes": t.done, "elapsed": elapsed,
                   "speed": t.done / elapsed if elapsed > 0 else 0.0, "message": message, **self._snapshot()})

    def callback(self, key: str) -> Callable[[int, int | None], None]:
        return lambda done, total: self.update(key, done, total)

    # ---------------------------------------------------------------- counters
    def step(self, **counters: Any) -> None:
        """Overall counters, e.g. record=3, records=12, files_seen=4000, hits=7."""
        with self.lock:
            self.counters.update(counters)
        self.emit({"kind": "step", **self._snapshot()})

    def _snapshot(self) -> dict[str, Any]:
        active = [{"name": t.name, "done": t.done, "total": t.total, "percent": t.percent(), "speed": t.speed(),
                   "eta": t.eta()} for t in self.active.values()]
        return {"active": active, "counters": dict(self.counters)}


# ---------------------------------------------------------------- formatting helpers
def human_bytes(n: float | None) -> str:
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def human_rate(bps: float | None) -> str:
    return "—" if not bps else human_bytes(bps) + "/s"


def human_time(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


def transfer_text(t: dict[str, Any], width: int = 28) -> str:
    """One transfer as ``name 45% 12.3 MB/40 MB 2.1 MB/s eta 14s``."""
    name = t["name"] if len(t["name"]) <= width else t["name"][: width - 1] + "…"
    if t.get("total"):
        return (f"{name} {t['percent']:3.0f}% {human_bytes(t['done'])}/{human_bytes(t['total'])} "
                f"{human_rate(t['speed'])} eta {human_time(t['eta'])}")
    return f"{name} {human_bytes(t['done'])} {human_rate(t['speed'])}"
