#!/usr/bin/env python3
"""Offline Deterministic Mock HTTP Server for Skill Watch and network testing.

Provides a lightweight, zero-dependency HTTP server thread using standard library
`http.server` to replay recorded upstream documentation fixtures (PyTorch, Lightning, etc.)
with deterministic headers, ETag caching, and chunked transfer encoding completely offline.
"""

from __future__ import annotations

import argparse
import contextlib
import http.server
import json
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class MockResponse:
    """Configured HTTP response for a specific route."""

    def __init__(
        self,
        body: bytes | str = b"",
        status: int = 200,
        headers: dict[str, str] | None = None,
        delay: float = 0.0,
    ) -> None:
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.status = status
        self.headers = {k: str(v) for k, v in (headers or {}).items()}
        self.delay = delay


class _MockRequestHandler(http.server.BaseHTTPRequestHandler):
    """Internal HTTP request handler dispatching to MockServer routes."""

    server: _MockHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress standard stderr request logging during test runs."""
        pass

    def do_GET(self) -> None:
        self._handle_request("GET")

    def do_HEAD(self) -> None:
        self._handle_request("HEAD")

    def _handle_request(self, method: str) -> None:
        # Record request for test assertions
        headers_dict = {k: v for k, v in self.headers.items()}
        parsed = urlsplit(self.path)
        path = parsed.path
        body = b""
        if "Content-Length" in self.headers:
            try:
                length = int(self.headers["Content-Length"])
                body = self.rfile.read(length)
            except (ValueError, OSError):
                pass

        self.server.mock_server.requests.append(
            {
                "method": method,
                "path": self.path,
                "pathname": path,
                "headers": headers_dict,
                "body": body,
            }
        )

        response = self.server.mock_server.match_route(path)
        if response is None:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "9")
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(b"Not Found")
            return

        if response.delay > 0:
            time.sleep(response.delay)

        # Check conditional request headers for HTTP 304 Not Modified
        if_none_match = self.headers.get("If-None-Match")
        route_etag = response.headers.get("ETag")
        if if_none_match and route_etag and if_none_match.strip() == route_etag.strip():
            self.send_response(304)
            for k, v in response.headers.items():
                if k.lower() in ("etag", "last-modified", "cache-control", "expires"):
                    self.send_header(k, v)
            self.end_headers()
            return

        if_modified_since = self.headers.get("If-Modified-Since")
        route_modified = response.headers.get("Last-Modified")
        if (
            if_modified_since
            and route_modified
            and if_modified_since.strip() == route_modified.strip()
        ):
            self.send_response(304)
            for k, v in response.headers.items():
                if k.lower() in ("etag", "last-modified", "cache-control", "expires"):
                    self.send_header(k, v)
            self.end_headers()
            return

        # Send configured status and headers
        self.send_response(response.status)
        is_chunked = response.headers.get("Transfer-Encoding", "").lower() == "chunked"

        for k, v in response.headers.items():
            if is_chunked and k.lower() == "content-length":
                continue  # Content-Length is omitted when Transfer-Encoding is chunked
            self.send_header(k, v)

        if not is_chunked and "Content-Length" not in response.headers:
            self.send_header("Content-Length", str(len(response.body)))
        if "Content-Type" not in response.headers:
            self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        if method == "HEAD":
            return

        if is_chunked:
            # Emit chunked transfer encoding frames
            chunk_size = 64
            for i in range(0, len(response.body), chunk_size):
                chunk = response.body[i : i + chunk_size]
                self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii"))
                self.wfile.write(chunk + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
        else:
            self.wfile.write(response.body)


class _MockHTTPServer(http.server.HTTPServer):
    """Custom HTTPServer linking back to parent MockServer instance."""

    def __init__(self, server_address: tuple[str, int], mock_server: MockServer) -> None:
        self.mock_server = mock_server
        super().__init__(server_address, _MockRequestHandler)


class MockServer:
    """Lightweight in-process HTTP mock server running on an ephemeral loopback port."""

    def __init__(
        self,
        routes: dict[str, MockResponse | dict[str, Any] | bytes | str] | None = None,
        fixtures_dir: str | Path | None = None,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self.host = host
        self.requested_port = port
        self.routes: dict[str, MockResponse] = {}
        self.requests: list[dict[str, Any]] = []
        self._server: _MockHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port: int = 0
        self.base_url: str = ""

        if routes:
            for path, target in routes.items():
                if isinstance(target, MockResponse):
                    self.routes[path] = target
                elif isinstance(target, dict):
                    self.register_route(
                        path,
                        body=target.get("body", b""),
                        status=target.get("status", 200),
                        headers=target.get("headers"),
                        delay=target.get("delay", 0.0),
                    )
                else:
                    self.register_route(path, body=target)

        if fixtures_dir:
            self.load_fixtures_dir(fixtures_dir)

    def register_route(
        self,
        path: str,
        body: bytes | str = b"",
        status: int = 200,
        headers: dict[str, str] | None = None,
        delay: float = 0.0,
    ) -> MockResponse:
        """Register a route path and its response."""
        clean_path = urlsplit(path).path if "://" in path else path
        if not clean_path.startswith("/"):
            clean_path = "/" + clean_path
        resp = MockResponse(body=body, status=status, headers=headers, delay=delay)
        self.routes[clean_path] = resp
        return resp

    def match_route(self, path: str) -> MockResponse | None:
        """Match request path against registered routes."""
        if path in self.routes:
            return self.routes[path]
        clean_path = path.rstrip("/")
        if clean_path in self.routes:
            return self.routes[clean_path]
        return None

    def load_fixture(self, filepath: str | Path) -> MockResponse:
        """Load a recorded JSON fixture and register its route."""
        path = Path(filepath)
        data = json.loads(path.read_text(encoding="utf-8"))
        url = data.get("url", "/" + path.stem)
        status = data.get("status", 200)
        headers = data.get("headers", {})
        body = data.get("body", "")
        delay = data.get("delay", 0.0)
        return self.register_route(url, body=body, status=status, headers=headers, delay=delay)

    def load_fixtures_dir(self, directory: str | Path) -> list[MockResponse]:
        """Load all .json fixtures from a directory."""
        dir_path = Path(directory)
        responses = []
        if dir_path.is_dir():
            for p in sorted(dir_path.glob("*.json")):
                responses.append(self.load_fixture(p))
        return responses

    def start(self) -> MockServer:
        """Start the background HTTP server thread."""
        if self._server is not None:
            return self
        self._server = _MockHTTPServer((self.host, self.requested_port), self)
        self.port = self._server.server_address[1]
        self.base_url = f"http://{self.host}:{self.port}"
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name=f"MockServer-{self.port}",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        """Shut down and release the server socket."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def __enter__(self) -> MockServer:
        return self.start()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()

    def url_for(self, path: str) -> str:
        """Return the complete local HTTP URL for a given path."""
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    @contextlib.contextmanager
    def patch_watch_fetch(self, wf_module: Any = None):
        """Context manager redirecting watch_fetch.PublicHTTPS to this local mock server.

        Directs socket connections and getaddrinfo to the mock server port,
        bypasses external DNS, and wraps TLS as plain socket pass-through for zero latency.
        """
        if wf_module is None:
            import watch_fetch as wf_module  # type: ignore

        orig_connect = wf_module.PublicHTTPS.connect
        server_port = self.port

        def mock_connect(conn: Any) -> None:
            # Connect directly to the local mock server over TCP
            raw = socket.create_connection(("127.0.0.1", server_port), timeout=conn.timeout)
            # Bypass TLS handshake for offline local mock testing
            conn.sock = raw

        wf_module.PublicHTTPS.connect = mock_connect  # type: ignore
        try:
            yield self
        finally:
            wf_module.PublicHTTPS.connect = orig_connect  # type: ignore


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic Offline Mock HTTP Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    parser.add_argument("--fixtures-dir", type=Path, help="Directory with .json fixtures")
    parser.add_argument("--fixture", type=Path, help="Single .json fixture to load")
    args = parser.parse_args()

    server = MockServer(host=args.host, port=args.port)
    if args.fixtures_dir:
        server.load_fixtures_dir(args.fixtures_dir)
    if args.fixture:
        server.load_fixture(args.fixture)

    print(f"Starting MockServer on {args.host}:{args.port}...")
    server.start()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopping MockServer...")
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
