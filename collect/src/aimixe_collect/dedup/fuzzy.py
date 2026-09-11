"""Fuzzy duplicate detection (specification §13, Phase 4).

Text-bearing resources get a bottom-k MinHash signature over word 5-shingles; Jaccard
similarity is estimated from signature overlap. Image and audio fingerprints are hooks:
``signature_for`` returns None for them and says why, so nothing pretends to compare.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

K = 128
SHINGLE = 5
_TOKEN = re.compile(r"\w+", re.UNICODE)


@dataclass
class Signature:
    kind: str                 # text-minhash
    values: list[int]         # sorted bottom-k hashes
    tokens: int


def text_signature(text: str, k: int = K, shingle: int = SHINGLE) -> Signature | None:
    tokens = [t.lower() for t in _TOKEN.findall(text)]
    if len(tokens) < shingle * 4:
        return None
    hashes: set[int] = set()
    for i in range(len(tokens) - shingle + 1):
        h = hashlib.blake2b(" ".join(tokens[i:i + shingle]).encode("utf-8"), digest_size=8).digest()
        hashes.add(int.from_bytes(h, "big"))
    return Signature("text-minhash", sorted(hashes)[:k], len(tokens))


def similarity(a: Signature, b: Signature, k: int = K) -> float:
    """Bottom-k estimate of Jaccard similarity."""
    if a.kind != b.kind or not a.values or not b.values:
        return 0.0
    union = sorted(set(a.values) | set(b.values))[:k]
    if not union:
        return 0.0
    both = set(a.values) & set(b.values)
    return sum(1 for v in union if v in both) / len(union)


def signature_for(kind_hint: str, text: str | None) -> tuple[Signature | None, str]:
    """Dispatch by resource kind. Returns (signature, note)."""
    if kind_hint in ("images",):
        return None, "image perceptual hashing needs an image decoder; not available in the standard library"
    if kind_hint in ("audio", "video"):
        return None, "audio fingerprinting needs a decoder (ffmpeg); not attempted"
    if text:
        sig = text_signature(text)
        return sig, "" if sig else "too little text for a signature"
    return None, "no text"
