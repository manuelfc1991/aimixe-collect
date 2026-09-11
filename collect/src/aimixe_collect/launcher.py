"""Cross-platform launcher: ``aimixe collect ...`` after ``pip install .`` (Windows, macOS, Linux).

``bin/aimixe`` is the same thing for Unix shells without installing.
"""
from __future__ import annotations

import sys

GROUPS = {"collect": "aimixe_collect.cli.main"}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print("usage: aimixe collect [language] [options]")
        print("       aimixe collect import <path> | history [id] | review | resume <id> | catalogue ... | ui")
        return 0 if argv else 40
    group, rest = argv[0], argv[1:]
    if group not in GROUPS:
        print(f"aimixe: unknown module group {group!r} (available: {', '.join(GROUPS)})", file=sys.stderr)
        return 40
    from importlib import import_module
    return int(import_module(GROUPS[group]).main(rest) or 0)


if __name__ == "__main__":
    sys.exit(main())
