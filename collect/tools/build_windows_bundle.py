"""Build a portable Windows bundle: unzip and run, no Python installation needed.

    python3 tools/build_windows_bundle.py [--python 3.13.7] [--out dist]

Downloads Python's official *embeddable* Windows build (a zip, no installer), adds this
module and an ``aimixe.cmd`` launcher, and produces ``dist/aimixe-collect-windows-<ver>.zip``.
The module needs only the standard library, so no pip step is required. Standard library
only here too; runs on Linux, macOS or Windows.

The bundle is built without a Windows machine and therefore untested until someone runs it
there; the bundle README says so.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "aimixe_collect"

LAUNCHER = """@echo off
rem AImixE Data Collection Module — portable launcher. Usage: aimixe collect [...]
setlocal
set "HERE=%~dp0"
set "PYTHONUTF8=1"
"%HERE%python\\python.exe" -X utf8 "%HERE%app\\run.py" %*
endlocal
"""

UI_LAUNCHER = """@echo off
rem Opens the local web interface in your browser.
setlocal
set "HERE=%~dp0"
set "PYTHONUTF8=1"
"%HERE%python\\python.exe" -X utf8 "%HERE%app\\run.py" collect ui
endlocal
"""

RUN_PY = """import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from aimixe_collect.launcher import main
sys.exit(main())
"""

README = """AImixE Data Collection Module — portable Windows bundle
=======================================================

No installation. Unzip this folder anywhere (for example C:\\aimixe) and double-click
aimixe-ui.cmd for the web interface, or open a terminal in the folder and run:

    aimixe collect
    aimixe collect nst --catalogue
    aimixe collect import C:\\path\\to\\folder
    aimixe collect ui

Your data is kept in %USERPROFILE%\\.aimixe (C:\\Users\\<you>\\.aimixe), not in this folder,
so you can delete or replace the folder without losing anything.

Contents
  python\\      Python {pyver} embeddable distribution from python.org (unmodified except
               python3xx._pth, which adds ..\\app to the import path)
  app\\         the aimixe_collect module and run.py
  aimixe.cmd   command-line launcher        aimixe-ui.cmd   opens the web interface

Notes
  * Built on {built_on}. This bundle was assembled without a Windows machine; if
    something fails, please report the exact message.
  * Windows may show a SmartScreen warning the first time a .cmd file runs; choose
    "More info" -> "Run anyway". Nothing here is signed.
  * The python.org zip's SHA-256 was {pysha}
  * Optional: install poppler's pdftotext and put it on PATH for better PDF text extraction.
"""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def build(pyver: str, out_dir: Path, arch: str = "amd64") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"aimixe-collect-windows-{arch}"
    bundle = out_dir / name
    if bundle.exists():
        shutil.rmtree(bundle)
    (bundle / "python").mkdir(parents=True)
    (bundle / "app").mkdir()

    # 1. Python embeddable distribution
    url = f"https://www.python.org/ftp/python/{pyver}/python-{pyver}-embed-{arch}.zip"
    pyzip = out_dir / f"python-{pyver}-embed-{arch}.zip"
    if not pyzip.exists():
        print(f"downloading {url}")
        with urllib.request.urlopen(url, timeout=120) as resp, pyzip.open("wb") as fh:
            shutil.copyfileobj(resp, fh)
    pysha = sha256(pyzip)
    with zipfile.ZipFile(pyzip) as zf:
        zf.extractall(bundle / "python")
    # the embeddable build reads sys.path from python3xx._pth; add our app folder
    pth = next((bundle / "python").glob("python*._pth"))
    lines = pth.read_text(encoding="utf-8").splitlines()
    lines.append("..\\app")
    pth.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 2. the module (source, data, web static), no caches or tests
    shutil.copytree(SRC, bundle / "app" / "aimixe_collect",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (bundle / "app" / "run.py").write_text(RUN_PY, encoding="utf-8")

    # 3. launchers and readme (CRLF so Notepad and cmd are happy)
    from datetime import date
    (bundle / "aimixe.cmd").write_bytes(LAUNCHER.replace("\n", "\r\n").encode("utf-8"))
    (bundle / "aimixe-ui.cmd").write_bytes(UI_LAUNCHER.replace("\n", "\r\n").encode("utf-8"))
    (bundle / "README.txt").write_bytes(
        README.format(pyver=pyver, built_on=date.today().isoformat(), pysha=pysha).replace("\n", "\r\n").encode("utf-8"))
    for extra in ("README.md", "PLAN.md"):
        if (ROOT / extra).exists():
            shutil.copy2(ROOT / extra, bundle / f"collect-{extra}")

    # 4. zip it
    zpath = out_dir / f"{name}-py{pyver}.zip"
    if zpath.exists():
        zpath.unlink()
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(bundle.rglob("*")):
            if f.is_file():
                zf.write(f, f"{name}/{f.relative_to(bundle).as_posix()}")
    print(f"bundle: {zpath}  ({zpath.stat().st_size / 1e6:.1f} MB)  sha256 {sha256(zpath)}")
    return zpath


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--python", default="3.13.7", help="python.org embeddable release (default 3.13.7)")
    ap.add_argument("--arch", default="amd64", choices=("amd64", "arm64", "win32"))
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ns = ap.parse_args()
    build(ns.python, Path(ns.out), ns.arch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
