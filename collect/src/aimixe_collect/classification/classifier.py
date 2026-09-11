"""Rule-based resource classifier. Multiple tags allowed; an agent may add its own later."""
from __future__ import annotations

from pathlib import Path

from ..language.registry import fold
from .formats import FormatInfo
from .resource_types import CATEGORY_TYPES, FORMAT_TYPES, KEYWORDS, RESOURCE_TYPES


def classify(path: Path | None, title: str | None, fmt: FormatInfo,
             hints: list[str] | None = None, metadata: dict | None = None) -> list[tuple[str, float, str]]:
    """Return ``[(type, confidence, source)]``; never empty (falls back to ``unknown``)."""
    scores: dict[str, float] = {}

    def bump(t: str, c: float) -> None:
        if t in RESOURCE_TYPES:
            scores[t] = max(scores.get(t, 0.0), c)

    if fmt.format in FORMAT_TYPES:
        bump(FORMAT_TYPES[fmt.format], 0.9)
    if fmt.category in CATEGORY_TYPES:
        bump(CATEGORY_TYPES[fmt.category], 0.95)

    texts: list[str] = []
    if path is not None:
        texts.append(path.stem)
        texts.extend(p.name for p in list(path.parents)[:3])
    if title:
        texts.append(title)
    if metadata:
        for k in ("title", "subject", "description", "type", "genre", "keywords"):
            v = metadata.get(k)
            if v:
                texts.append(str(v))
    blob = " " + fold(" ".join(texts)) + " "
    for kw, t in KEYWORDS.items():
        if f" {kw} " in blob or f" {kw}s " in blob or (len(kw) > 6 and kw in blob):
            bump(t, 0.7)

    for h in hints or []:
        hf = fold(h).replace(" ", "_")
        if hf in RESOURCE_TYPES:
            bump(hf, 0.8)
        else:
            for kw, t in KEYWORDS.items():
                if kw in fold(h):
                    bump(t, 0.6)

    if fmt.category == "documents" and not scores:
        bump("research", 0.3)
    if not scores:
        bump("unknown", 0.5)
    return [(t, c, "rule") for t, c in sorted(scores.items(), key=lambda kv: -kv[1])]
