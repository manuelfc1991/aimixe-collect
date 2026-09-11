"""Command-line entry point (specification §21).

    aimixe collect
    aimixe collect <language> [--online] [--offline] [--catalogue] [--agent]
                              [--scan PATH ...] [--import PATH] [--profile] [--mode copy|move|reference] [--yes]
    aimixe collect import <path> [--language <id>] [--mode copy|move|reference]
    aimixe collect history [<session-id>]
    aimixe collect review [--language <id>]
    aimixe collect resume <session-id>

Exit codes: 0 success · 10 own check failed · 20 not evaluable · 40 invalid input ·
50 configuration · 70 internal.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..services.app import App
from . import interactive, render as r
from .render import Abort
from .review_ui import run_review

SUBCOMMANDS = ("import", "history", "review", "resume", "catalogue", "ui")

EXIT_OK, EXIT_CHECK_FAILED, EXIT_NOT_EVALUABLE, EXIT_INVALID, EXIT_CONFIG, EXIT_INTERNAL = 0, 10, 20, 40, 50, 70


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aimixe collect", description="AImixE Data Collection Module",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  aimixe collect                      interactive: name a language, build its profile, collect
  aimixe collect nst                  start with a language (name, ISO 639-3 code or alias)
  aimixe collect nst --catalogue      search catalogues, then download what scores high enough
  aimixe collect nst --agent          web search planned from the profile (rule-based or a model CLI)
  aimixe collect nst --scan ~/Docs    offline: find files on this machine about the language
  aimixe collect import grammar.pdf   add a file or folder (copy | move | reference)
  aimixe collect review               accept or reject uncertain resources and proposed facts
  aimixe collect history              past collection sessions
  aimixe collect catalogue list       catalogue providers (add | remove)
  aimixe collect ui                   the same, in your browser
in any menu: number or text to choose, b = back, q = quit, ? = help.""")
    p.add_argument("--version", action="version", version="aimixe collect 0.1.0")
    p.add_argument("--no-color", action="store_true", help="plain output (also honoured: NO_COLOR)")
    p.add_argument("language", nargs="?", help="language name or ISO 639-3 code")
    p.add_argument("--online", action="store_true", help="online collection menu")
    p.add_argument("--offline", action="store_true", help="offline collection (asks for folders)")
    p.add_argument("--catalogue", action="store_true", help="catalogue search")
    p.add_argument("--agent", action="store_true", help="agent search")
    p.add_argument("--scan", metavar="PATH", action="append", help="offline scan of PATH (repeatable)")
    p.add_argument("--import", dest="import_path", metavar="PATH", help="import a file or folder")
    p.add_argument("--profile", action="store_true", help="language profile menu")
    p.add_argument("--mode", choices=("copy", "move", "reference"), help="storage mode for scan/import")
    p.add_argument("--yes", "-y", action="store_true", help="accept the detected language without asking")
    p.add_argument("--home", metavar="DIR", help="AImixE home directory (default ~/.aimixe or $AIMIXE_HOME)")
    return p


def build_sub_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--home", metavar="DIR", help="AImixE home directory")
    common.add_argument("--no-color", action="store_true", help="plain output")
    p = argparse.ArgumentParser(prog="aimixe collect", parents=[common])
    sub = p.add_subparsers(dest="command", required=True)

    imp = sub.add_parser("import", help="import a file or folder", parents=[common])
    imp.add_argument("path")
    imp.add_argument("--language", "-l", help="language name or ISO 639-3 code (asked if omitted)")
    imp.add_argument("--mode", choices=("copy", "move", "reference"))
    imp.add_argument("--yes", "-y", action="store_true")

    hist = sub.add_parser("history", help="list collection sessions", parents=[common])
    hist.add_argument("session_id", nargs="?")
    hist.add_argument("--language", "-l")
    hist.add_argument("--json", action="store_true")

    rev = sub.add_parser("review", help="review uncertain resources and proposed profile facts", parents=[common])
    rev.add_argument("--language", "-l")

    res = sub.add_parser("resume", help="re-run an interrupted session with the same parameters", parents=[common])
    res.add_argument("session_id")

    ui = sub.add_parser("ui", help="local web interface on the same services (Phase 5)", parents=[common])
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--no-browser", action="store_true", help="do not open a browser tab")

    cat = sub.add_parser("catalogue", help="manage catalogue providers", parents=[common])
    catsub = cat.add_subparsers(dest="cat_command", required=True)
    cadd = catsub.add_parser("add", help="add a custom catalogue (guided, or from a TOML file)", parents=[common])
    cadd.add_argument("--file", help="TOML file describing the catalogue")
    catsub.add_parser("list", help="list catalogue providers", parents=[common])
    crm = catsub.add_parser("remove", help="remove a custom catalogue or disable a built-in one", parents=[common])
    crm.add_argument("name")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower().replace("-", "") != "utf8":
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    try:
        if argv and argv[0] in SUBCOMMANDS:
            return _run_sub(argv)
        return _run_main(argv)
    except (Abort, r.Back):
        r.out("Bye.")
        return EXIT_OK
    except KeyboardInterrupt:
        r.out()
        return EXIT_OK
    except FileNotFoundError as exc:
        r.err(f"Not found: {exc}")
        return EXIT_INVALID
    except ValueError as exc:
        r.err(f"Invalid input: {exc}")
        return EXIT_INVALID


def _run_main(argv: list[str]) -> int:
    ns = build_parser().parse_args(argv)
    if ns.no_color:
        r.set_color(False)
    home = Path(ns.home).expanduser() if ns.home else None
    with App(home) as app:
        if not ns.language:
            return interactive.run_interactive(app)
        profile = interactive.pick_language(app, ns.language, assume_yes=ns.yes)
        if profile is None:
            return EXIT_INVALID
        did_something = False
        if ns.profile:
            interactive.profile_step(app, profile, force_menu=True)
            profile = app.language_service.load(profile.id) or profile
            did_something = True
        if ns.scan:
            roots = [Path(p).expanduser() for p in ns.scan]
            interactive.offline_collection(app, profile, roots=roots, mode=ns.mode or app.config.storage_mode)
            did_something = True
        if ns.offline:
            interactive.offline_collection(app, profile, mode=ns.mode)
            did_something = True
        if ns.import_path:
            path = Path(ns.import_path).expanduser()
            if not path.exists():
                r.err(f"Not found: {path}")
                return EXIT_INVALID
            interactive.run_import(app, profile, path, ns.mode)
            did_something = True
        if ns.catalogue:
            interactive.catalogue_search(app, profile, assume_yes=ns.yes)
            did_something = True
        if ns.agent:
            interactive.agent_search(app, profile, assume_yes=ns.yes)
            did_something = True
        if ns.online:
            interactive.online_menu(app, profile)
            did_something = True
        if not did_something:
            interactive.profile_step(app, profile)
            profile = app.language_service.load(profile.id) or profile
            interactive.main_menu(app, profile)
        return EXIT_OK


def _run_sub(argv: list[str]) -> int:
    ns = build_sub_parser().parse_args(argv)
    if getattr(ns, "no_color", False):
        r.set_color(False)
    home = Path(ns.home).expanduser() if getattr(ns, "home", None) else None
    if ns.command == "ui":
        from ..web.server import serve
        try:
            serve(home, host=ns.host, port=ns.port, open_browser=not ns.no_browser)
        except OSError as exc:
            r.err(f"Cannot start the interface on {ns.host}:{ns.port}: {exc}")
            return EXIT_CONFIG
        return EXIT_OK
    with App(home) as app:
        if ns.command == "import":
            path = Path(ns.path).expanduser()
            if not path.exists():
                r.err(f"Not found: {path}")
                return EXIT_INVALID
            profile = interactive.pick_language(app, ns.language, assume_yes=ns.yes or bool(ns.language))
            if profile is None:
                return EXIT_INVALID
            summary = interactive.run_import(app, profile, path, ns.mode)
            return EXIT_OK if summary.failed == 0 else EXIT_CHECK_FAILED

        if ns.command == "history":
            if ns.session_id:
                s = app.history_service.get(ns.session_id)
                if s is None:
                    r.err(f"No session {ns.session_id}")
                    return EXIT_INVALID
                interactive.print_summary(s)
                for ev in app.history_service.events(ns.session_id):
                    r.out(f"  {ev['ts']}  {ev['level']:5}  {ev['message']}")
                return EXIT_OK
            sessions = app.history_service.list(ns.language)
            if ns.json:
                r.out(json.dumps([s.__dict__ for s in sessions], indent=2))
                return EXIT_OK
            if not sessions:
                r.out("No collection sessions yet.")
                return EXIT_OK
            r.table([[s.id, f"{s.language_name} [{s.language_id}]", s.mode, s.status, s.started_at[:19],
                      str(s.discovered), str(s.relevant), str(s.downloaded), str(s.duplicates), str(s.failed),
                      str(s.pending_review)] for s in sessions],
                    headers=["session", "language", "mode", "status", "started", "disc", "rel", "down", "dup", "fail", "review"])
            return EXIT_OK

        if ns.command == "review":
            lid = None
            if ns.language:
                res = app.language_service.resolve(ns.language)
                if res.best is None:
                    r.err(f"Unknown language {ns.language}")
                    return EXIT_INVALID
                lid = res.best.language_id
            run_review(app, lid)
            return EXIT_OK

        if ns.command == "resume":
            return _resume(app, ns.session_id)

        if ns.command == "catalogue":
            return _catalogue(app, ns)
    return EXIT_INTERNAL


def _catalogue(app: App, ns) -> int:
    svc = app.catalogue_service
    if ns.cat_command == "list":
        rows = [[e.name, e.provider.kind, "yes" if e.enabled else "no",
                 "built-in" if e.source == "builtin" else e.source, e.provider.description[:60]]
                for e in svc.list()]
        r.table(rows, headers=["name", "kind", "enabled", "source", "what"])
        for err in svc.registry.errors:
            r.err(f"! {err}")
        return EXIT_OK
    if ns.cat_command == "remove":
        try:
            r.out(svc.remove(ns.name))
        except ValueError as exc:
            r.err(str(exc))
            return EXIT_INVALID
        return EXIT_OK
    if ns.cat_command == "add":
        if ns.file:
            import tomllib
            path = Path(ns.file).expanduser()
            if not path.exists():
                r.err(f"Not found: {path}")
                return EXIT_INVALID
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            cfgs = data.get("catalogue") if isinstance(data.get("catalogue"), list) else [data]
        else:
            cfgs = [interactive.catalogue_add_wizard()]
            if cfgs[0] is None:
                return EXIT_OK
        for cfg in cfgs:
            try:
                written = svc.add(cfg)
            except ValueError as exc:
                r.err(f"Invalid catalogue: {exc}")
                return EXIT_INVALID
            r.out(f"Catalogue {cfg['name']} saved to {written}")
        return EXIT_OK
    return EXIT_INVALID


def _resume(app: App, session_id: str) -> int:
    row = app.sessions.get(session_id)
    if row is None:
        r.err(f"No session {session_id}")
        return EXIT_INVALID
    if row["status"] not in ("interrupted", "failed"):
        r.out(f"Session {session_id} is {row['status']}; nothing to resume.")
        return EXIT_NOT_EVALUABLE
    profile = app.language_service.load(row["language_id"])
    if profile is None:
        return EXIT_INVALID
    params = json.loads(row["params_json"] or "{}")
    r.out(f"Resuming {session_id} ({row['mode']}) for {profile.name}. Already-stored files are linked as duplicates.")
    if row["mode"] == "Offline Collection":
        roots = [Path(p) for p in params.get("roots", [])]
        summary = interactive.offline_collection(app, profile, roots=roots, mode=params.get("storage_mode"))
    elif row["mode"] == "Import":
        summary = interactive.run_import(app, profile, Path(params["target"]), params.get("mode"))
    else:
        r.out("Only Offline Collection and Import sessions can be resumed in this build.")
        return EXIT_NOT_EVALUABLE
    if summary:
        app.sessions.event(summary.id, "info", f"resumed from {session_id}")
        app.sessions.commit()
    return EXIT_OK
