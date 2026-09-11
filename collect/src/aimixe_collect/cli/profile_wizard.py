"""Language Profile enrichment wizard (specification §2): grouped, progressive, skippable."""
from __future__ import annotations

import re
from typing import Any

from ..profile import schema
from ..profile.model import Profile
from ..profile.parse import NO_WORDS, UNKNOWN_WORDS, YES_WORDS, entry_from_text as _entry_from_text, \
    parse_speakers as _parse_speakers, split_list as _split_list
from ..services.app import App
from ..services.profile_service import ProfileStatus
from . import render as r
from .render import Abort

class ProfileWizard:
    def __init__(self, app: App, profile: Profile, session_id: str | None = None):
        self.app = app
        self.profile = profile
        self.session_id = session_id
        self.svc = app.profile_service

    # ------------------------------------------------------------- progress
    def show_progress(self, status: ProfileStatus, current: str | None) -> None:
        r.heading("Language Profile")
        r.out("✓ Basic identification")
        for g in schema.GROUPS:
            state = status.group_state(g.name)
            if g.name == current:
                glyph = "●"
            elif state == "done":
                glyph = "✓"
            else:
                glyph = "○"
            r.out(f"{glyph} {g.progress_label}")
        r.out()

    # ------------------------------------------------------------- summaries
    def show_known_missing(self, status: ProfileStatus) -> None:
        r.heading("Language profile found." if status.known else "Language profile is empty.")
        if status.known:
            r.out("Known:")
            for g, f in status.known:
                mark = "?" if (g, f) in status.uncertain or (g, f) in status.contradictory else "✓"
                r.out(f"{mark} {schema.field_spec(g, f).label}")
            r.out()
        if status.to_ask:
            r.out("Missing:" if not (status.uncertain or status.contradictory) else "Missing or uncertain:")
            for g, f in status.to_ask:
                r.out(f"- {schema.field_spec(g, f).label}")
            r.out()

    def review(self) -> None:
        """Review existing profile: every field with its value and provenance."""
        r.heading(f"Language Profile – {self.profile.name} [{self.profile.iso639_3 or self.profile.id}]")
        for g in schema.GROUPS:
            r.out(f"{g.title}")
            for f in g.fields:
                vals = self.profile.field_values(g.name, f.name, include_proposed=True)
                if not vals:
                    r.out(f"  {f.label}: —")
                    continue
                if f.multi:
                    r.out(f"  {f.label}: {r.fmt_value(self.profile.collected(g.name, f.name))}")
                else:
                    r.out(f"  {f.label}: {r.fmt_value(self.profile.display_value(g.name, f.name))}")
                for v in vals:
                    flag = "*" if v.preferred else " "
                    st = "" if v.status == "accepted" else f" [{v.status}]"
                    src = v.source or v.source_type
                    r.out(f"     {flag} {r.fmt_value(v.value)}  — {v.source_type}: {src}"
                          f"{f' ({v.year})' if v.year else ''}, confidence {v.confidence:.2f}{st}")
            r.out()

    # ------------------------------------------------------------- asking
    def run(self, fields: list[tuple[str, str]], status: ProfileStatus) -> int:
        """Ask the given fields group by group. Returns the number of values recorded."""
        recorded = 0
        by_group: dict[str, list[str]] = {}
        for g, f in fields:
            by_group.setdefault(g, []).append(f)
        r.out("Leave a field blank to skip it. Type ? for help. Ctrl-C leaves the profile step.")
        try:
            for g in schema.GROUPS:
                if g.name not in by_group:
                    continue
                self.show_progress(status, g.name)
                r.heading(f"Language Profile – {g.title}")
                for fname in by_group[g.name]:
                    spec = schema.field_spec(g.name, fname)
                    if self.ask_field(g.name, spec):
                        recorded += 1
                status = self.svc.status(self.profile)
        except Abort:
            r.out("Profile step left; answers so far are saved.")
        return recorded

    def ask_field(self, group: str, spec: schema.FieldSpec) -> bool:
        current = self.profile.display_value(group, spec.name)
        if current not in (None, [], {}):
            conf = self.profile.confidence(group, spec.name)
            src = self.profile.preferred(group, spec.name)
            r.out(f"(current: {r.fmt_value(current)} — {src.source_type if src else '?'}, confidence {conf:.2f})")
        value = self._ask_kind(group, spec)
        if value is None:
            return False
        self.svc.set_value(self.profile, group, spec.name, value, session_id=self.session_id)
        return True

    def _prompt(self, spec: schema.FieldSpec, label: str | None = None) -> str:
        while True:
            ans = r.prompt(label or spec.prompt)
            if ans == "?":
                if spec.help:
                    r.out(spec.help)
                if spec.suggested:
                    r.out("Suggested values: " + ", ".join(spec.suggested))
                if not spec.help and not spec.suggested:
                    r.out("Free text. Leave blank to skip.")
                continue
            return ans

    def _ask_kind(self, group: str, spec: schema.FieldSpec) -> Any:
        kind = spec.kind
        if kind == "text":
            ans = self._prompt(spec)
            return ans or None
        if kind == "list":
            if spec.suggested:
                r.out(spec.prompt)
                for i, v in enumerate(spec.suggested, 1):
                    r.out(f"  {i}. {v}")
                r.out("  (numbers and/or your own words, comma separated)")
                ans = self._prompt(spec, label="")
                items = []
                for raw in _split_list(ans):
                    if raw.isdigit() and 1 <= int(raw) <= len(spec.suggested):
                        items.append(spec.suggested[int(raw) - 1])
                    else:
                        items.append(raw)
                return items or None
            return _split_list(self._prompt(spec)) or None
        if kind == "choice":
            return self._ask_choice(spec)
        if kind == "state":
            return self._ask_state(spec)
        if kind == "speakers":
            return _parse_speakers(self._prompt(spec))
        if kind == "scripts":
            names = _split_list(self._prompt(spec))
            out = []
            for n in names:
                s = self.app.registry.script(n)
                out.append({"code": s.code if s else None, "name": s.name if s else n, "as_entered": n})
            return out or None
        if kind == "parent":
            ans = self._prompt(spec)
            if not ans:
                return None
            r.out("Type of grouping (" + ", ".join(f"{i}={t}" for i, t in enumerate(spec.suggested, 1)) + "), or blank:")
            t = r.prompt()
            ptype = spec.suggested[int(t) - 1] if t.isdigit() and 1 <= int(t) <= len(spec.suggested) else (t or None)
            return {"value": ans, "type": ptype}
        if kind == "places":
            return self._ask_places(spec)
        if kind == "tagged_list":
            ans = self._prompt(spec)
            items = []
            for raw in _split_list(ans):
                m = re.match(r"^(.*?)\s*(?:\((.*?)\)|:\s*(.*))$", raw)
                if m and (m.group(2) or m.group(3)):
                    items.append({"name": m.group(1).strip(), "role": (m.group(2) or m.group(3)).strip()})
                else:
                    items.append({"name": raw})
            return items or None
        if kind == "basis":
            return self._ask_basis(spec)
        if kind == "age_spread":
            return self._ask_age_spread(spec)
        if kind == "entries":
            return self._ask_entries(spec)
        if kind == "community":
            return self._ask_community(spec)
        ans = self._prompt(spec)
        return ans or None

    def _ask_choice(self, spec: schema.FieldSpec) -> Any:
        r.out(spec.prompt)
        for i, v in enumerate(spec.suggested, 1):
            r.out(f"  {i}. {v}")
        r.out("  (or describe in your own words)")
        ans = self._prompt(spec, label="")
        if not ans:
            return None
        if ans.isdigit() and 1 <= int(ans) <= len(spec.suggested):
            return spec.suggested[int(ans) - 1]
        low = ans.lower().replace(" ", "_")
        for v in spec.suggested:
            if low == v.lower():
                return v
        return ans

    def _ask_state(self, spec: schema.FieldSpec) -> Any:
        ans = self._prompt(spec)
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

    def _ask_places(self, spec: schema.FieldSpec) -> Any:
        r.out(spec.prompt)
        r.out("One place per line as: name, type, region, country. Blank line to finish.")
        places = []
        while True:
            ans = self._prompt(spec, label="")
            if not ans:
                break
            parts = [p.strip() for p in ans.split(",")]
            place = {"name": parts[0]}
            if len(parts) > 1 and parts[1]:
                place["type"] = parts[1]
            if len(parts) > 2 and parts[2]:
                place["region"] = parts[2]
            if len(parts) > 3 and parts[3]:
                place["country"] = parts[3]
            places.append(place)
        return places or None

    def _ask_basis(self, spec: schema.FieldSpec) -> Any:
        r.out(spec.prompt)
        for i, v in enumerate(spec.suggested, 1):
            r.out(f"  {i}. {v}")
        ans = self._prompt(spec, label="")
        if not ans:
            return None
        btype = spec.suggested[int(ans) - 1] if ans.isdigit() and 1 <= int(ans) <= len(spec.suggested) else ans
        year = r.prompt("Year of the estimate (blank if unknown):")
        source = r.prompt("Source (e.g. Census of India, author, organisation):")
        out: dict[str, Any] = {"type": btype}
        if year.isdigit():
            out["year"] = int(year)
        if source:
            out["source"] = source
        return out

    def _ask_age_spread(self, spec: schema.FieldSpec) -> Any:
        r.out(spec.prompt)
        r.out("Answer yes / no / unknown for each group. Blank to skip the whole field.")
        out: dict[str, Any] = {}
        first = True
        for key, label in (("children", "Children"), ("young_adults", "Young adults"),
                           ("adults", "Adults"), ("elderly", "Elderly")):
            ans = r.prompt(f"{label}:").lower()
            if first and not ans:
                return None
            first = False
            if ans in YES_WORDS:
                out[key] = True
            elif ans in NO_WORDS:
                out[key] = False
            else:
                out[key] = "unknown" if not ans or ans in UNKNOWN_WORDS else ans
        note = r.prompt("Additional detail (optional):")
        if note:
            out["note"] = note
        return out

    def _ask_entries(self, spec: schema.FieldSpec) -> Any:
        ans = self._prompt(spec)
        if not ans:
            return None
        low = ans.lower()
        if low in NO_WORDS:
            return [{"state": "no"}]
        if low in UNKNOWN_WORDS:
            return [{"state": "unknown"}]
        entries: list[dict[str, Any]] = []
        if low not in YES_WORDS:
            entries.append(_entry_from_text(ans, spec.suggested))
        r.out("Add entries (kind or title; blank to finish). Kinds: " + ", ".join(spec.suggested))
        while True:
            kind = r.prompt("Kind / title:")
            if not kind:
                break
            e = _entry_from_text(kind, spec.suggested)
            title = r.prompt("Title (blank if none):")
            date = r.prompt("Date / year:")
            org = r.prompt("Organisation / publisher:")
            url = r.prompt("URL:")
            if title:
                e["title"] = title
            if date:
                e["date"] = date
            if org:
                e["organisation"] = org
            if url:
                e["url"] = url
            entries.append(e)
        return entries or [{"state": "yes"}]

    def _ask_community(self, spec: schema.FieldSpec) -> Any:
        ans = self._prompt(spec)
        if not ans:
            return None
        out: dict[str, Any] = {"text": ans}
        if r.ask_yes_no("Add structured details (community names, organizations, committees, ...)?", default=False):
            for aspect in spec.suggested:
                vals = _split_list(r.prompt(f"{aspect.capitalize()} (comma separated, blank to skip):"))
                if vals:
                    out[aspect] = vals
        return out
