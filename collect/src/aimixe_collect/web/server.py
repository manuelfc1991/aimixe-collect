"""Local web interface: ``aimixe collect ui`` (specification Phase 5, same services as the CLI).

Standard-library HTTP server bound to localhost. Static files come from the package; every
``/api/...`` call goes through :class:`Api`.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources as ilr
from pathlib import Path

from .api import Api, ApiError, dumps
from .jobs import JobManager

STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "application/javascript; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8")}


def make_handler(api: Api):
    class Handler(BaseHTTPRequestHandler):
        server_version = "aimixe-collect-ui/0.1"

        def log_message(self, fmt, *args):  # quiet by default
            if "--verbose" in sys.argv:
                super().log_message(fmt, *args)

        def _send(self, status: int, body: bytes, ctype: str = "application/json; charset=utf-8") -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _api(self, method: str) -> None:
            u = urllib.parse.urlparse(self.path)
            query = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            body = {}
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                try:
                    body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    self._send(400, dumps({"error": "invalid JSON body"}))
                    return
            try:
                result = api.handle(method, u.path, query, body)
                self._send(200, dumps(result))
            except ApiError as exc:
                self._send(exc.status, dumps({"error": exc.message}))
            except Exception as exc:  # never leak a traceback page; report the error as JSON
                self._send(500, dumps({"error": f"{type(exc).__name__}: {exc}"}))

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path.startswith("/api/"):
                return self._api("GET")
            if u.path in STATIC:
                name, ctype = STATIC[u.path]
                data = ilr.files("aimixe_collect.web").joinpath("static").joinpath(name).read_bytes()
                return self._send(200, data, ctype)
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            self._api("POST")

        def do_DELETE(self):
            self._api("DELETE")

    return Handler


def serve(home: Path | None = None, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True,
          ready: threading.Event | None = None) -> ThreadingHTTPServer:
    api = Api(home, JobManager())
    server = ThreadingHTTPServer((host, port), make_handler(api))
    url = f"http://{host}:{server.server_address[1]}/"
    print(f"AImixE Data Collection interface: {url}   (Ctrl-C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    if ready is not None:
        ready.set()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return server
