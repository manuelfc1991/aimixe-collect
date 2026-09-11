"""The bundled user guide (a single HTML file) and how to open it."""
from __future__ import annotations

import webbrowser
from importlib import resources as ilr
from pathlib import Path

GUIDE_NAME = "user-guide.html"


def guide_path() -> Path:
    """Where the guide lives on this machine (inside the installed package)."""
    return Path(str(ilr.files("aimixe_collect.docs").joinpath(GUIDE_NAME)))


def guide_bytes() -> bytes:
    return ilr.files("aimixe_collect.docs").joinpath(GUIDE_NAME).read_bytes()


def open_guide(anchor: str | None = None) -> tuple[bool, str]:
    """Open the guide in the default browser. Returns (opened, url_or_path)."""
    url = guide_path().resolve().as_uri() + (f"#{anchor}" if anchor else "")
    try:
        return bool(webbrowser.open(url)), url
    except Exception:
        return False, url
