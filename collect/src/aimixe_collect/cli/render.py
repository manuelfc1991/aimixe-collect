"""Terminal prompts and printing. Presentation only — no application logic here."""
from __future__ import annotations

import sys
from collections.abc import Sequence


class Abort(Exception):
    """The user ended input (Ctrl-D / Ctrl-C)."""


def out(text: str = "") -> None:
    print(text)


def heading(text: str) -> None:
    print()
    print(text)
    print()


def prompt(label: str = "", *, default: str | None = None) -> str:
    """Show ``label`` on its own line and read one line after ``> ``, as in the specification."""
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
    raw = raw.strip()
    if not raw and default is not None:
        return default
    return raw


def ask_yes_no(question: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        ans = prompt(f"{question} {suffix}").lower()
        if not ans:
            return default
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        out("Please answer y or n.")


def choose(title: str, options: Sequence[str], *, allow_blank: bool = False) -> int | None:
    """Numbered menu; returns the 0-based index, or None when blank is allowed and given."""
    heading(title)
    for i, opt in enumerate(options, 1):
        out(f"{i}. {opt}")
    out()
    while True:
        ans = prompt("Select:")
        if not ans and allow_blank:
            return None
        if ans.isdigit() and 1 <= int(ans) <= len(options):
            return int(ans) - 1
        # accept the option text itself
        for i, opt in enumerate(options):
            if ans.lower() == opt.lower():
                return i
        out(f"Enter a number between 1 and {len(options)}.")


def table(rows: Sequence[Sequence[str]], headers: Sequence[str] | None = None) -> None:
    if headers:
        rows = [list(headers)] + [list(r) for r in rows]
    if not rows:
        return
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    for n, r in enumerate(rows):
        out("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)).rstrip())
        if headers and n == 0:
            out("  ".join("-" * w for w in widths))


class ProgressBoard:
    """One terminal status line, redrawn in place, showing counters and active transfers.

    Ordinary messages printed through ``print_line`` clear the status line first so the
    log stays readable; the status is redrawn afterwards.
    """

    def __init__(self, enabled: bool | None = None):
        self.enabled = sys.stdout.isatty() if enabled is None else enabled
        self.last: dict = {}
        self._width = 0
        self._lock = __import__("threading").Lock()

    def handle(self, event: dict) -> None:
        from ..progress import human_bytes, human_rate, human_time, transfer_text
        with self._lock:
            if event.get("kind") == "done":
                self._clear()
                name = event["name"] if len(event["name"]) <= 60 else event["name"][:59] + "…"
                if event.get("ok"):
                    print(f"  ✓ {name}  {human_bytes(event['bytes'])} in {human_time(event['elapsed'])} "
                          f"({human_rate(event['speed'])})")
                else:
                    print(f"  ✗ {name}  {event.get('message', '')[:100]}")
            self.last = event
            self._draw()

    def status_text(self) -> str:
        from ..progress import transfer_text
        ev = self.last
        if not ev:
            return ""
        c = ev.get("counters", {})
        bits = []
        if c.get("stage"):
            bits.append(str(c["stage"]))
        if c.get("records"):
            bits.append(f"record {c.get('record', 0)}/{c['records']}")
        if c.get("files"):
            bits.append(f"file {c.get('file', 0)}/{c['files']}")
        if c.get("max_pages"):
            bits.append(f"pages {c.get('pages', 0)}/{c['max_pages']}")
        if c.get("files_seen") is not None and "records" not in c:
            bits.append(f"{c['files_seen']} files seen, {c.get('hits', 0)} match(es)")
        if c.get("import_total"):
            bits.append(f"{c.get('import_done', 0)}/{c['import_total']} imported")
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
        cols = __import__("shutil").get_terminal_size((100, 20)).columns - 1
        text = text[:cols]
        pad = " " * max(0, self._width - len(text))
        sys.stdout.write("\r" + text + pad)
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


def err(text: str) -> None:
    print(text, file=sys.stderr)


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
            extra = [str(value[k]) for k in ("type", "region", "country") if value.get(k)]
            return parts[0] + (f" ({', '.join(extra)})" if extra else "")
        if "code" in value and "name" in value:
            return f"{value['name']} [{value['code']}]"
        if "value" in value:
            extra = [str(value[k]) for k in ("type", "detail", "code") if value.get(k)]
            return str(value["value"]) + (f" ({', '.join(extra)})" if extra else "")
        if "min" in value and "max" in value:
            return f"{value['min']}–{value['max']}"
        if "title" in value or "kind" in value:
            bits = [str(value[k]) for k in ("kind", "title", "date", "organisation", "url") if value.get(k)]
            return " · ".join(bits)
        return "; ".join(f"{k}: {fmt_value(v)}" for k, v in value.items() if v not in (None, "", [], {}))
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)
