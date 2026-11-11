#!/usr/bin/env python3
"""Serve Maintainer Studio and its read-only API at http://127.0.0.1:8765.

Run with Python 3.11+: python3 tools/studio_server.py [--port PORT].
Production assets are shipped in apps/studio/static; no Node runtime is needed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

if __name__ == "__main__":
    # Standalone startup must not create repository bytecode caches.
    sys.dont_write_bytecode = True

if __package__:
    from . import kit
else:
    import kit


HOST = "127.0.0.1"
PORT = 8765
FRONTEND = kit.ROOT / "apps/studio/static"
FRONTEND_MISSING = (
    "Studio frontend is missing. Restore apps/studio/static or see docs/studio.md to rebuild."
)
ASSET_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


def _frontend_bytes(directory: Path, relative: str) -> bytes:
    # Do not resolve symlinks before checking each component of the asset root.
    root = directory.absolute()
    kit.checked_path(Path(root.anchor), root.relative_to(root.anchor).as_posix())
    path = kit.checked_path(root, relative)
    if not path.is_file():
        raise FileNotFoundError(relative)
    return path.read_bytes()


class StudioHandler(BaseHTTPRequestHandler):
    """Explicit routes only: no filesystem paths or mutation commands."""

    def parse_request(self):
        if not super().parse_request():
            return False
        hosts = self.headers.get_all("Host", [])
        port = self.server.server_address[1]
        allowed = {"127.0.0.1", "localhost", f"127.0.0.1:{port}", f"localhost:{port}"}
        # Validate the original authority, never proxy headers or resolved DNS.
        if len(hosts) != 1 or hosts[0].lower() not in allowed:
            self.send_error(403, "Host must identify this local server")
            return False
        return True

    def _send_json(self, status: int, payload: dict, *, allow: str | None = None):
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if allow is not None:
            self.send_header("Allow", allow)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_error(self, code, message=None, explain=None):
        # BaseHTTPRequestHandler routes unimplemented methods through error 501.
        # Return consistent JSON, including errors detected by its HTTP parser.
        if code == 501:
            code, message = 405, "Method not allowed"
        self.close_connection = True
        self._send_json(
            code,
            {"error": message or self.responses.get(code, ("Error",))[0]},
            allow="GET" if code == 405 else None,
        )

    def do_GET(self):
        try:
            target = urlsplit(self.path)
        except ValueError:
            self.send_error(400, "Invalid request target")
            return
        if target.scheme or target.netloc or target.fragment:
            self.send_error(400, "Expected a local request path")
            return
        if target.path == "/api" or target.path.startswith("/api/"):
            self._serve_api(target.path)
        else:
            self._serve_frontend(target.path)

    def _serve_api(self, path: str):
        if path == "/api/health":
            self._send_json(200, {"status": "ok"})
        elif path == "/api/profile":
            try:
                # Preserve kit's schema, ordering and tokenizer/heuristic label.
                profile = kit.profile_tokens()
                self._send_json(200, profile)
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception:
                self.send_error(500, "Unable to load token profile")
        else:
            self.send_error(404, "Not found")

    def _serve_frontend(self, path: str):
        try:
            decoded = unquote(path, errors="strict")
        except UnicodeError:
            self.send_error(404, "Not found")
            return
        if decoded in {"/", "/index.html"}:
            relative, content_type = "index.html", "text/html; charset=utf-8"
        elif decoded == "/favicon.svg":
            relative, content_type = "favicon.svg", ASSET_TYPES[".svg"]
        elif decoded == "/THIRD_PARTY_NOTICES.txt":
            relative, content_type = "THIRD_PARTY_NOTICES.txt", "text/plain; charset=utf-8"
        elif re.fullmatch(r"/assets/[A-Za-z0-9_.-]+\.[a-z0-9]+", decoded):
            relative = decoded[1:]
            content_type = ASSET_TYPES.get(Path(relative).suffix)
            if content_type is None:
                self.send_error(404, "Not found")
                return
        else:
            # No SPA fallback, source maps, directory listings or repository files.
            self.send_error(404, "Not found")
            return
        try:
            body = _frontend_bytes(self.server.frontend_dir, relative)
        except FileNotFoundError:
            self.send_error(
                503 if relative == "index.html" else 404,
                FRONTEND_MISSING if relative == "index.html" else "Not found",
            )
            return
        except kit.KitError:
            self.send_error(404, "Not found")
            return
        except OSError:
            self.send_error(500, "Unable to read frontend asset")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(body)


def create_server(port: int = PORT, *, frontend_dir: Path = FRONTEND) -> ThreadingHTTPServer:
    """Bind IPv4 loopback only; port 0 lets tests request an ephemeral port."""
    server = ThreadingHTTPServer((HOST, port), StudioHandler)
    server.frontend_dir = frontend_dir
    return server


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Port must be an integer") from exc
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("Port must be between 0 and 65535")
    return port


def _open_browser(url: str):
    try:
        opened = webbrowser.open(url, new=2)
    except Exception:
        opened = False
    if not opened:
        print(f"Could not open a browser. Open {url} manually.", file=sys.stderr)


def main(
    argv: list[str] | None = None,
    *,
    open_browser: bool = False,
    require_frontend: bool = False,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=_port, default=PORT)
    args = parser.parse_args(argv)
    if require_frontend:
        try:
            _frontend_bytes(FRONTEND, "index.html")
        except (OSError, kit.KitError):
            print(FRONTEND_MISSING, file=sys.stderr)
            return 1
    try:
        with create_server(args.port) as server:
            host, port = server.server_address
            url = f"http://{host}:{port}"
            print(f"Maintainer Studio: {url} (read-only)", flush=True)
            if open_browser:
                # The socket is already listening; browser startup cannot block HTTP.
                threading.Thread(target=_open_browser, args=(url,), daemon=True).start()
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        print(f"Studio server error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
