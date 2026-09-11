"""Bundled language registry: ISO 639-3, ISO 15924 and the Glottolog-derived reference table.

Works with no network. Matching folds case and diacritics. ``find()`` returns candidates;
it never guesses on the caller's behalf.
"""
from __future__ import annotations

import csv
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources as ilr
from pathlib import Path

DATA_PKG = "aimixe_collect.data"


def fold(text: str) -> str:
    """Lowercase, strip diacritics and punctuation noise, collapse whitespace."""
    norm = unicodedata.normalize("NFKD", text or "")
    chars = []
    for ch in norm:
        if unicodedata.combining(ch):
            continue
        if ch in "'’`´-_/(),.":
            chars.append(" ")
        else:
            chars.append(ch.lower())
    return " ".join("".join(chars).split())


def _open(name: str):
    return ilr.files(DATA_PKG).joinpath(name).open("r", encoding="utf-8", newline="")


@dataclass
class ScriptRecord:
    code: str
    number: str
    name: str


@dataclass
class LanguageRecord:
    code: str                       # ISO 639-3
    ref_name: str
    scope: str = ""                 # I individual, M macrolanguage, S special
    language_type: str = ""         # L living, E extinct, ...
    names: list[str] = field(default_factory=list)       # ISO name index (print names)
    glottocode: str = ""
    glottolog_name: str = ""
    family: str = ""
    classification: str = ""
    macroarea: str = ""
    countries: list[str] = field(default_factory=list)   # ISO 3166-1 alpha-2
    dialects: list[str] = field(default_factory=list)
    alt_names: list[str] = field(default_factory=list)   # Glottolog names
    likely_script: str = ""
    endangerment: str = ""          # Glottolog AES
    documentation: str = ""         # Glottolog MED
    macrolanguage: str = ""         # parent macrolanguage code, if member
    members: list[str] = field(default_factory=list)      # if this is a macrolanguage

    @property
    def display_name(self) -> str:
        return self.ref_name or self.glottolog_name

    def all_names(self) -> list[str]:
        seen: dict[str, str] = {}
        for n in [self.ref_name, self.glottolog_name, *self.names, *self.alt_names]:
            if n and fold(n) not in seen:
                seen[fold(n)] = n
        return list(seen.values())

    def alternative_names(self) -> list[str]:
        primary = fold(self.display_name)
        return [n for n in self.all_names() if fold(n) != primary]


@dataclass
class Candidate:
    record: LanguageRecord
    matched_on: str      # code | name | alternate_name | dialect | retired_code
    matched_text: str
    score: float         # 1.0 exact, lower for weaker matches


class Registry:
    def __init__(self) -> None:
        self.languages: dict[str, LanguageRecord] = {}
        self.scripts: dict[str, ScriptRecord] = {}
        self.retired: dict[str, tuple[str, str]] = {}       # old code -> (change_to, reason)
        self.countries: dict[str, str] = {}
        self._name_index: dict[str, list[tuple[str, str, str]]] = {}   # folded -> [(code, kind, text)]
        self._load()

    # ------------------------------------------------------------------ loading
    def _load(self) -> None:
        with _open("iso-639-3.tab") as fh:
            for row in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
                rec = LanguageRecord(code=row["Id"], ref_name=row["Ref_Name"],
                                     scope=row["Scope"], language_type=row["Language_Type"])
                self.languages[rec.code] = rec
        with _open("iso-639-3_Name_Index.tab") as fh:
            for row in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
                rec = self.languages.get(row["Id"])
                if rec is None:
                    continue
                for n in (row.get("Print_Name"), row.get("Inverted_Name")):
                    if n and n not in rec.names and n != rec.ref_name:
                        rec.names.append(n)
        with _open("iso-639-3_Retirements.tab") as fh:
            for row in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
                self.retired[row["Id"]] = (row.get("Change_To") or "", row.get("Ret_Reason") or "")
        with _open("iso-639-3-macrolanguages.tab") as fh:
            for row in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
                macro, member = row["M_Id"], row["I_Id"]
                if member in self.languages:
                    self.languages[member].macrolanguage = macro
                if macro in self.languages:
                    self.languages[macro].members.append(member)
        with _open("reference.csv") as fh:
            for row in csv.DictReader(fh):
                rec = self.languages.get(row["iso"])
                if rec is None:
                    continue
                rec.glottocode = row.get("glottocode", "")
                rec.glottolog_name = row.get("name", "")
                rec.family = row.get("family", "")
                rec.classification = row.get("classification", "")
                rec.macroarea = row.get("macroarea", "")
                rec.countries = [c for c in (row.get("countries") or "").split(";") if c]
                rec.dialects = [d for d in (row.get("dialects") or "").split("|") if d]
                rec.alt_names = [n for n in (row.get("names") or "").split("|") if n]
                rec.likely_script = row.get("likely_script", "")
                rec.endangerment = row.get("aes", "")
                rec.documentation = row.get("med", "")
        with _open("iso15924.txt") as fh:
            for line in fh:
                if not line.strip() or line.startswith("#"):
                    continue
                parts = line.rstrip("\n").split(";")
                if len(parts) >= 3:
                    self.scripts[parts[0]] = ScriptRecord(code=parts[0], number=parts[1], name=parts[2])
        with _open("countries.tsv") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                self.countries[row["alpha_2"]] = row["name"]
        # name index
        for rec in self.languages.values():
            self._index(rec.ref_name, rec.code, "name")
            if rec.glottolog_name:
                self._index(rec.glottolog_name, rec.code, "name")
            for n in rec.names + rec.alt_names:
                self._index(n, rec.code, "alternate_name")
            for d in rec.dialects:
                self._index(d, rec.code, "dialect")

    def _index(self, text: str, code: str, kind: str) -> None:
        key = fold(text)
        if not key:
            return
        bucket = self._name_index.setdefault(key, [])
        if not any(c == code and k == kind for c, k, _ in bucket):
            bucket.append((code, kind, text))

    # ------------------------------------------------------------------ lookup
    def by_code(self, code: str) -> LanguageRecord | None:
        return self.languages.get(code.strip().lower())

    def retirement(self, code: str) -> tuple[str, str] | None:
        return self.retired.get(code.strip().lower())

    def country_name(self, alpha2: str) -> str:
        return self.countries.get(alpha2.upper(), alpha2)

    def region_text(self, rec: LanguageRecord) -> str:
        names = [self.country_name(c) for c in rec.countries]
        return " / ".join(names)

    def script(self, code_or_name: str) -> ScriptRecord | None:
        q = code_or_name.strip()
        if not q:
            return None
        if q[:1].upper() + q[1:].lower() in self.scripts and len(q) == 4:
            return self.scripts[q[:1].upper() + q[1:].lower()]
        fq = fold(q)
        for s in self.scripts.values():
            if fold(s.name) == fq:
                return s
        for s in self.scripts.values():
            if fq and fq in fold(s.name):
                return s
        return None

    def ambiguous_name(self, name: str, threshold: int = 3) -> bool:
        """True when ``name`` is listed for several languages (e.g. "Zhuang", "Naga", "Chin")."""
        bucket = self._name_index.get(fold(name), [])
        return len({code for code, _, _ in bucket}) >= threshold

    def find(self, query: str, limit: int = 12) -> list[Candidate]:
        """Candidates for a name, ISO code, alternative name or dialect name."""
        q = (query or "").strip()
        if not q:
            return []
        out: list[Candidate] = []
        seen: set[str] = set()

        def add(rec: LanguageRecord, kind: str, text: str, score: float) -> None:
            if rec.code in seen:
                return
            seen.add(rec.code)
            out.append(Candidate(record=rec, matched_on=kind, matched_text=text, score=score))

        lower = q.lower()
        if len(lower) == 3 and lower.isalpha():
            rec = self.by_code(lower)
            if rec:
                add(rec, "code", lower, 1.0)
            ret = self.retirement(lower)
            if ret and ret[0] and ret[0] in self.languages:
                add(self.languages[ret[0]], "retired_code", f"{lower} → {ret[0]}", 0.9)

        fq = fold(q)
        rank = {"name": 0.98, "alternate_name": 0.9, "dialect": 0.8}
        for code, kind, text in self._name_index.get(fq, []):
            add(self.languages[code], kind, text, rank[kind])

        # "X language" / "language X" spellings
        stripped = " ".join(w for w in fq.split() if w not in ("language", "jezik", "langue"))
        if stripped and stripped != fq:
            for code, kind, text in self._name_index.get(stripped, []):
                add(self.languages[code], kind, text, rank[kind] - 0.02)

        if len(out) < limit and len(fq) >= 3:
            for key, bucket in self._name_index.items():
                if key.startswith(fq) or (len(fq) >= 5 and fq in key):
                    for code, kind, text in bucket:
                        add(self.languages[code], kind, text, rank[kind] - 0.35)
                        if len(out) >= limit * 3:
                            break
        out.sort(key=lambda c: (-c.score, c.record.display_name))
        return out[:limit]


@lru_cache(maxsize=1)
def load_registry() -> Registry:
    return Registry()


def data_file(name: str) -> Path:
    return Path(str(ilr.files(DATA_PKG).joinpath(name)))
