"""Build the single-file user guide shipped inside the package.

    python3 tools/build_user_guide.py

Reads docs/guide/user-guide.src.html, inlines every <img src="images/..."> as a data URI and
writes src/aimixe_collect/docs/user-guide.html (what `aimixe collect guide`, the terminal's
`g` key, the web sidebar and the Windows bundle open). Standard library only.
"""
from __future__ import annotations

import base64
import mimetypes
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "guide" / "user-guide.src.html"
OUT = ROOT / "src" / "aimixe_collect" / "docs" / "user-guide.html"


def build() -> Path:
    html = SRC.read_text(encoding="utf-8")
    missing: list[str] = []

    def inline(m: re.Match) -> str:
        rel = m.group(2)
        path = SRC.parent / rel
        if not path.exists():
            missing.append(rel)
            return m.group(0)
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return f'{m.group(1)}data:{ctype};base64,{data}{m.group(3)}'

    out = re.sub(r'(<img[^>]*\ssrc=")(images/[^"]+)(")', inline, html)
    if missing:
        sys.exit("missing images: " + ", ".join(missing))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(out, encoding="utf-8")
    return OUT


if __name__ == "__main__":
    p = build()
    print(f"wrote {p} ({p.stat().st_size // 1024} KB)")
