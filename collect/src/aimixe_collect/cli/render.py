"""Terminal prompts and printing. Presentation only — no application logic here.

Colour is on when stdout is a terminal and neither ``NO_COLOR`` nor ``--no-color`` is set.
Every menu accepts a number, the option text, ``b``/``back`` and ``q``/``quit``; Enter takes
the remembered or given default. ``?`` at a prompt prints its help.
"""
from __future__ import annotations

import os
import shutil
import sys
import threading
from collections.abc import Sequence


class Abort(Exception):
    """The user ended input (Ctrl-D / Ctrl-C / quit)."""


class Back(Exception):
    """The user asked to go back one screen."""


BACK = object()

# ------------------------------------------------------------------ colour
_FORCE: bool | None = None            # set by --no-color / --color


def set_color(enabled: bool | None) -> None:
    global _FORCE
    _FORCE = enabled


def color_enabled() -> bool:
    if _FORCE is not None:
        return _FORCE
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


_CODES = {"bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33", "blue": "34",
          "magenta": "35", "cyan": "36", "grey": "90"}


def c(text: str, *styles: str) -> str:
    if not color_enabled() or not styles:
        return text
    return "".join(f"\033[{_CODES[s]}m" for s in styles if s in _CODES) + text + "\033[0m"


def band_color(score: int | None) -> str:
    if score is None:
        return "grey"
    if score >= 70:
        return "green"
    if score >= 50:
        return "yellow"
    if score >= 30:
        return "yellow"
    return "grey"


def score_text(score: int | None, band_label: str | None = None) -> str:
    if score is None:
        return c("—", "grey")
    s = f"{score:3}"
    if band_label:
        s += f" {band_label}"
    return c(s, band_color(score), "bold" if score >= 70 else "dim" if score < 30 else "")


STATUS_STYLE = {"stored": ("stored", "green"), "duplicate_linked": ("duplicate", "grey"),
                "uncertain_review": ("review", "yellow"), "rejected": ("skipped", "grey"), "failed": ("FAILED", "red")}


def term_width(default: int = 100) -> int:
    return shutil.get_terminal_size((default, 24)).columns


# ------------------------------------------------------------------ output
def out(text: str = "") -> None:
    print(text)


def heading(text: str) -> None:
    print()
    print(c(text, "bold"))
    print()


def header(language: str | None = None, iso: str | None = None, resources: int | None = None,
           pending_review: int | None = None) -> None:
    """One muted line at the top of a screen: where you are and what you have."""
    bits = []
    if language:
        bits.append(f"{language} [{iso or '—'}]")
    if resources is not None:
        bits.append(f"{resources} resource(s)")
    if pending_review:
        bits.append(c(f"{pending_review} pending review", "yellow"))
    bits.append("b = back · q = quit · ? = help")
    print(c("  ".join(b if b.startswith("\033") else b for b in bits), "grey"))


def err(text: str) -> None:
    print(c(text, "red"), file=sys.stderr)


def note(text: str) -> None:
    print(c(text, "grey"))


# ------------------------------------------------------------------ input
def _read(label: str) -> str:
    try:
        if label:
            print(label)
        raw = input("> ")
    except EOFError as exc:
        print()
        raise Abort() from exc
    except KeyboardInterrupt as exc:
        print()
        raise Abort() from exc
    return raw.strip()


def prompt(label: str = "", *, default: str | None = None, help: str | None = None,
           allow_back: bool = False) -> str:
    """Show ``label`` on its own line and read one line after ``> ``, as in the specification.

    ``?`` prints ``help`` and asks again; ``q``/``quit`` ends the program; with ``allow_back``,
    ``b``/``back`` raises :class:`Back`.
    """
    while True:
        raw = _read(label)
        low = raw.lower()
        if raw == "?":
            print(c(help or "Type an answer, or leave blank to skip.", "grey"))
            continue
        if low in ("q", "quit", "exit"):
            raise Abort()
        if allow_back and low in ("b", "back"):
            raise Back()
        if not raw and default is not None:
            return default
        return raw


def ask_yes_no(question: str, default: bool = True, help: str | None = None) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        ans = prompt(f"{question} {suffix}", help=help).lower()
        if not ans:
            return default
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        out("Please answer y or n.")


_last_choice: dict[str, int] = {}


def choose(title: str, options: Sequence[str], *, allow_blank: bool = False, default: int | None = None,
           remember: bool = True, allow_back: bool = False, help: str | None = None) -> int | None:
    """Numbered menu; returns the 0-based index (None when blank is allowed and given).

    Enter takes the default: the given one, else the last choice made in this menu.
    ``b``/``back`` raises :class:`Back` when allowed; ``q`` quits.
    """
    heading(title)
    key = title.split("\n")[0]
    if default is None and remember:
        default = _last_choice.get(key)
    for i, opt in enumerate(options, 1):
        mark = c("›", "cyan", "bold") if default == i - 1 else " "
        out(f"{mark}{i}. {opt}")
    out()
    while True:
        ans = prompt("Select:", help=help or "Enter a number, part of an option's text, b for back, q to quit.")
        low = ans.lower()
        if not ans:
            if default is not None:
                return default
            if allow_blank:
                return None
            continue
        if low in ("b", "back"):
            if allow_back:
                raise Back()
            back_idx = next((i for i, o in enumerate(options) if o.strip().lower() in ("back", "exit", "keep current")), None)
            if back_idx is not None:
                return back_idx
        if ans.isdigit() and 1 <= int(ans) <= len(options):
            idx = int(ans) - 1
        else:
            matches = [i for i, opt in enumerate(options) if opt.lower().startswith(low)] or \
                      [i for i, opt in enumerate(options) if low in opt.lower()]
            if len(matches) != 1:
                out(f"Enter a number between 1 and {len(options)}" + (" (or b / q)." if allow_back else "."))
                continue
            idx = matches[0]
        if remember:
            _last_choice[key] = idx
        return idx


# ------------------------------------------------------------------ tables
_ANSI_RE = __import__("re").compile(r"\033\[[0-9;]*m")


def _vlen(text: str) -> int:
    return len(_ANSI_RE.sub("", text))


def _cut(text: str, width: int) -> str:
    """Truncate to ``width`` visible characters, keeping escape codes balanced."""
    if _vlen(text) <= width:
        return text
    plain = _ANSI_RE.sub("", text)
    if plain == text:
        return text[: max(1, width - 1)] + "…"
    return plain[: max(1, width - 1)] + "…"          # drop colour rather than risk a broken sequence


def table(rows: Sequence[Sequence[str]], headers: Sequence[str] | None = None, max_width: int | None = None) -> None:
    """Aligned table that fits the terminal: the widest columns are truncated with an ellipsis."""
    body = [list(map(str, r)) for r in rows]
    if headers:
        body = [list(headers)] + body
    if not body:
        return
    ncol = len(body[0])
    widths = [max(_vlen(r[i]) if i < len(r) else 0 for r in body) for i in range(ncol)]
    try:
        is_tty = sys.stdout.isatty()
    except (AttributeError, ValueError):
        is_tty = False
    limit = (max_width or (term_width() if is_tty else 10**6)) - 2 * (ncol - 1)
    # only long text columns (titles, names) give way; ids, modes and numbers keep their width
    while sum(widths) > limit and max(widths) > 24:
        i = widths.index(max(widths))
        widths[i] -= 1
    for n, r in enumerate(body):
        cells = []
        for i in range(ncol):
            cell = _cut(r[i] if i < len(r) else "", widths[i])
            cells.append(cell + " " * (widths[i] - _vlen(cell)))
        line = "  ".join(cells).rstrip()
        out(c(line, "bold", "grey") if headers and n == 0 else line)
        if headers and n == 0:
            out(c("  ".join("-" * w for w in widths), "grey"))


def fmt_value(value) -> str:
    """Compact, human-readable rendering of a stored profile value."""
    if value is None or value == [] or value == {}:
        return "—"
    if isinstance(value, list):
        return ", ".join(fmt_value(v) for v in value)
    if isinstance(value, dict):
        if "state" in value:
            return value["state"] + (f" ({value['detail']})" if value.get("detail") else "")
        if "name" in value:
            parts = [str(value["name"])]
            extra = [str(value[k]) for k in ("type", "region", "country", "role") if value.get(k)]
            return parts[0] + (f" ({', '.join(extra)})" if extra else "")
        if "code" in value and "name" in value:
            return f"{value['name']} [{value['code']}]"
        if "value" in value:
            extra = [str(value[k]) for k in ("type", "detail", "code") if value.get(k)]
            return str(value["value"]) + (" (approx.)" if value.get("approximate") else "") + (f" ({', '.join(extra)})" if extra else "")
        if "min" in value and "max" in value:
            return f"{value['min']}–{value['max']}"
        if "title" in value or "kind" in value:
            bits = [str(value[k]) for k in ("kind", "title", "date", "organisation", "url") if value.get(k)]
            return " · ".join(bits)
        return "; ".join(f"{k}: {fmt_value(v)}" for k, v in value.items() if v not in (None, "", [], {}))
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


# ------------------------------------------------------------------ progress
class ProgressBoard:
    """One terminal status line, redrawn in place, showing counters and active transfers.

    Ordinary messages printed through ``print_line`` clear the status line first so the
    log stays readable; the status is redrawn afterwards.
    """

    def __init__(self, enabled: bool | None = None):
        self.enabled = sys.stdout.isatty() if enabled is None else enabled
        self.last: dict = {}
        self._width = 0
        self._lock = threading.Lock()

    def handle(self, event: dict) -> None:
        from ..progress import human_bytes, human_rate, human_time
        with self._lock:
            if event.get("kind") == "done":
                self._clear()
                name = event["name"] if len(event["name"]) <= 60 else event["name"][:59] + "…"
                if event.get("ok"):
                    print(f"  {c('✓', 'green')} {name}  {human_bytes(event['bytes'])} in {human_time(event['elapsed'])} "
                          f"({human_rate(event['speed'])})")
                else:
                    print(f"  {c('✗', 'red')} {name}  {event.get('message', '')[:100]}")
            self.last = event
            self._draw()

    def status_text(self) -> str:
        from ..progress import transfer_text
        ev = self.last
        if not ev:
            return ""
        cnt = ev.get("counters", {})
        bits = []
        if cnt.get("stage"):
            bits.append(str(cnt["stage"]))
        if cnt.get("records"):
            bits.append(f"record {cnt.get('record', 0)}/{cnt['records']}")
        if cnt.get("files"):
            bits.append(f"file {cnt.get('file', 0)}/{cnt['files']}")
        if cnt.get("max_pages"):
            bits.append(f"pages {cnt.get('pages', 0)}/{cnt['max_pages']}")
        if cnt.get("files_seen") is not None and "records" not in cnt:
            bits.append(f"{cnt['files_seen']} files seen, {cnt.get('hits', 0)} match(es)")
        if cnt.get("import_total"):
            bits.append(f"{cnt.get('import_done', 0)}/{cnt['import_total']} imported")
        active = ev.get("active", [])
        if active:
            bits.append(f"↓ {len(active)}: " + " · ".join(transfer_text(t, 22) for t in active[:3]))
            if len(active) > 3:
                bits.append(f"+{len(active) - 3} more")
        return "  ".join(bits)

    def _draw(self) -> None:
        if not self.enabled:
            return
        text = self.status_text()
        if not text:
            return
        cols = term_width() - 1
        text = text[:cols]
        pad = " " * max(0, self._width - len(text))
        sys.stdout.write("\r" + c(text, "cyan") + pad)
        sys.stdout.flush()
        self._width = len(text)

    def _clear(self) -> None:
        if self.enabled and self._width:
            sys.stdout.write("\r" + " " * self._width + "\r")
            sys.stdout.flush()
            self._width = 0

    def print_line(self, text: str = "") -> None:
        with self._lock:
            self._clear()
            print(text)
            self._draw()

    def finish(self) -> None:
        with self._lock:
            self._clear()
            self.last = {}
