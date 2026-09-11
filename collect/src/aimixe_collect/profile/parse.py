"""Parse user input into profile values, per field kind (shared by the CLI wizard and the web UI)."""
from __future__ import annotations

import re
from typing import Any

from . import schema

YES_WORDS = {"y", "yes", "true", "available", "exist", "exists"}
NO_WORDS = {"n", "no", "none", "false", "not available"}
UNKNOWN_WORDS = {"unknown", "?", "unsure", "dont know", "don't know", "not sure"}


def split_list(text: str) -> list[str]:
    if not text:
        return []
    return [p.strip() for p in re.split(r"[;,\n]", text) if p.strip()]


def parse_speakers(text: str) -> Any:
    if not text:
        return None
    t = text.replace(",", "").strip()
    m = re.match(r"^~\s*(\d+)$", t)
    if m:
        return {"value": int(m.group(1)), "approximate": True}
    m = re.match(r"^(\d+)\s*[-–]\s*(\d+)$", t)
    if m:
        return {"min": int(m.group(1)), "max": int(m.group(2))}
    if t.isdigit():
        return int(t)
    return {"text": text}


def parse_state(text: str) -> Any:
    ans = (text or "").strip()
    if not ans:
        return None
    low = ans.lower()
    first, _, rest = ans.partition(" ")
    fl = first.lower().strip(":,-")
    if fl in schema.AVAILABILITY_STATES:
        return {"state": fl, "detail": rest.strip(" :-") or None}
    if low in YES_WORDS:
        return {"state": "yes", "detail": None}
    if low in NO_WORDS:
        return {"state": "no", "detail": None}
    if low in UNKNOWN_WORDS:
        return {"state": "unknown", "detail": None}
    return {"state": "reported", "detail": ans}


def parse_choice(spec: schema.FieldSpec, text: str) -> Any:
    ans = (text or "").strip()
    if not ans:
        return None
    if ans.isdigit() and 1 <= int(ans) <= len(spec.suggested):
        return spec.suggested[int(ans) - 1]
    low = ans.lower().replace(" ", "_")
    for v in spec.suggested:
        if low == v.lower():
            return v
    return ans


def parse_tagged_list(text: str) -> Any:
    items = []
    for raw in split_list(text):
        m = re.match(r"^(.*?)\s*(?:\((.*?)\)|:\s*(.*))$", raw)
        if m and (m.group(2) or m.group(3)):
            items.append({"name": m.group(1).strip(), "role": (m.group(2) or m.group(3)).strip()})
        else:
            items.append({"name": raw})
    return items or None


def parse_places(lines: str) -> Any:
    places = []
    for line in (lines or "").splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        place = {"name": parts[0]}
        for i, key in enumerate(("type", "region", "country"), 1):
            if len(parts) > i and parts[i]:
                place[key] = parts[i]
        places.append(place)
    return places or None


def parse_list_with_suggestions(spec: schema.FieldSpec, text: str) -> Any:
    items = []
    for raw in split_list(text):
        if spec.suggested and raw.isdigit() and 1 <= int(raw) <= len(spec.suggested):
            items.append(spec.suggested[int(raw) - 1])
        else:
            items.append(raw)
    return items or None


def entry_from_text(text: str, kinds: tuple[str, ...]) -> dict[str, Any]:
    low = text.lower()
    for k in kinds:
        if k.lower() == low:
            return {"kind": k}
        if k.lower() in low:
            return {"kind": k, "title": text}
    return {"title": text}


def parse_entries(spec: schema.FieldSpec, lines: str) -> Any:
    """One entry per line: ``kind | title | date | organisation | url``; or no / unknown."""
    text = (lines or "").strip()
    if not text:
        return None
    low = text.lower()
    if low in NO_WORDS:
        return [{"state": "no"}]
    if low in UNKNOWN_WORDS:
        return [{"state": "unknown"}]
    if low in YES_WORDS:
        return [{"state": "yes"}]
    entries = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split("|")]
        e = entry_from_text(parts[0], spec.suggested)
        for i, key in enumerate(("title", "date", "organisation", "url", "note"), 1):
            if len(parts) > i and parts[i]:
                e[key] = parts[i]
        entries.append(e)
    return entries or None


def parse_form(spec: schema.FieldSpec, form: dict[str, Any], scripts_lookup=None) -> Any:
    """Turn a web form's fields (all strings) into the stored value for ``spec``."""
    kind = spec.kind
    v = (form.get("value") or "").strip() if isinstance(form.get("value"), str) else form.get("value")
    if kind == "text":
        return v or None
    if kind == "list":
        return parse_list_with_suggestions(spec, v or "")
    if kind == "choice":
        return parse_choice(spec, v or "")
    if kind == "state":
        st = (form.get("state") or "").strip()
        detail = (form.get("detail") or "").strip() or None
        if st:
            return {"state": st, "detail": detail}
        return parse_state(v or "")
    if kind == "speakers":
        return parse_speakers(v or "")
    if kind == "scripts":
        out = []
        for n in split_list(v or ""):
            s = scripts_lookup(n) if scripts_lookup else None
            out.append({"code": s.code if s else None, "name": s.name if s else n, "as_entered": n})
        return out or None
    if kind == "parent":
        if not v:
            return None
        return {"value": v, "type": (form.get("type") or "").strip() or None}
    if kind == "places":
        return parse_places(v or "")
    if kind == "tagged_list":
        return parse_tagged_list(v or "")
    if kind == "basis":
        t = (form.get("type") or v or "").strip()
        if not t:
            return None
        out: dict[str, Any] = {"type": t}
        year = (form.get("year") or "").strip()
        if year.isdigit():
            out["year"] = int(year)
        if (form.get("source") or "").strip():
            out["source"] = form["source"].strip()
        return out
    if kind == "age_spread":
        out = {}
        any_set = False
        for key in ("children", "young_adults", "adults", "elderly"):
            a = (form.get(key) or "").strip().lower()
            if not a:
                continue
            any_set = True
            out[key] = True if a in YES_WORDS else False if a in NO_WORDS else a
        if (form.get("note") or "").strip():
            out["note"] = form["note"].strip()
            any_set = True
        return out if any_set else None
    if kind == "entries":
        return parse_entries(spec, v or "")
    if kind == "community":
        if not v:
            return None
        out = {"text": v}
        for aspect in spec.suggested:
            key = aspect.replace(" ", "_")
            vals = split_list(form.get(key) or "")
            if vals:
                out[aspect] = vals
        return out
    return v or None
