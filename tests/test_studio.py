import io
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import Mock, patch

from tools import studio_server as studio


class StudioEndpointTests(unittest.TestCase):
    def setUp(self):
        logging = patch.object(studio.StudioHandler, "log_message")
        logging.start()
        self.addCleanup(logging.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.frontend = Path(temporary.name).resolve()
        (self.frontend / "assets").mkdir()
        (self.frontend / "index.html").write_text(
            '<html><div id="root"></div></html>', encoding="utf-8"
        )
        (self.frontend / "assets/app-123.js").write_text(
            "console.log('fixture');", encoding="utf-8"
        )
        (self.frontend / "assets/app-123.css").write_text(
            "body { color: green; }", encoding="utf-8"
        )
        (self.frontend / "favicon.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8"
        )
        (self.frontend / "THIRD_PARTY_NOTICES.txt").write_text("Fixture notices", encoding="utf-8")
        self.server = studio.create_server(port=0, frontend_dir=self.frontend)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, method="GET", path="/api/health", body=None):
        connection = HTTPConnection(*self.server.server_address, timeout=30)
        try:
            # Avoid client-side URL parsing so malformed targets reach the server.
            host, port = self.server.server_address
            connection.request(method, path, body=body, headers={"Host": f"{host}:{port}"})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_health_is_json_and_does_not_profile(self):
        with patch.object(studio.kit, "profile_tokens") as profile:
            status, headers, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"status": "ok"})
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(int(headers["Content-Length"]), len(body))
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        profile.assert_not_called()

    def test_profile_preserves_complete_payload_and_calls_kit_without_arguments(self):
        payload = {
            "encoding": "cl100k_base (heuristic ~4 chars/tok)",
            "skills": [{"name": "mkl-example", "warnings": ["Polish: zażółć"], "tokens": 900}],
            "agents": [{"name": "mkl-agent", "total_tokens": 1000}],
            "targets": {"cursor": {"files": 2, "total_tokens": 1900}},
            "summary": {"skills_count": 1, "agents_count": 1},
            "future_field": {"preserved": True},
        }
        with patch.object(studio.kit, "profile_tokens", return_value=payload) as profile:
            status, headers, body = self.request(path="/api/profile")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), payload)
        self.assertEqual(int(headers["Content-Length"]), len(body))
        profile.assert_called_once_with()

    def test_profile_matches_real_kit_data_and_preserves_stdlib_fallback(self):
        def repository_snapshot():
            root = studio.kit.ROOT
            files = [path for path in root.iterdir() if path.is_file()]
            for name in ("skills", "agents", "providers", "assets", ".claude-plugin", "tools"):
                files.extend(path for path in (root / name).rglob("*") if path.is_file())
            return {path.relative_to(root).as_posix(): path.read_bytes() for path in files}

        before = repository_snapshot()
        with patch.dict("sys.modules", {"tiktoken": None}):
            expected = studio.kit.profile_tokens()
            status, _, body = self.request(path="/api/profile")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), expected)
        self.assertIn("heuristic ~4 chars/tok", json.loads(body)["encoding"])
        self.assertEqual(repository_snapshot(), before)

    def test_profile_is_recomputed_instead_of_cached(self):
        with patch.object(
            studio.kit, "profile_tokens", side_effect=[{"revision": 1}, {"revision": 2}]
        ) as profile:
            self.assertEqual(json.loads(self.request(path="/api/profile")[2]), {"revision": 1})
            self.assertEqual(json.loads(self.request(path="/api/profile")[2]), {"revision": 2})
        self.assertEqual(profile.call_count, 2)

    def test_profile_failures_return_safe_json_and_server_remains_available(self):
        for error in (
            studio.kit.KitError("private repository path"),
            OSError("private filesystem details"),
            RuntimeError("unexpected details"),
        ):
            with (
                self.subTest(error=error),
                patch.object(studio.kit, "profile_tokens", side_effect=error),
            ):
                status, _, body = self.request(path="/api/profile")
            self.assertEqual(status, 500)
            self.assertEqual(json.loads(body), {"error": "Unable to load token profile"})
            self.assertNotIn(str(error), body.decode())
            self.assertEqual(self.request()[0], 200)

    def test_unserializable_profile_returns_error_before_success_headers(self):
        with patch.object(studio.kit, "profile_tokens", return_value={"invalid": object()}):
            status, _, body = self.request(path="/api/profile")
        self.assertEqual(status, 500)
        self.assertEqual(json.loads(body), {"error": "Unable to load token profile"})

    def test_unknown_paths_and_traversal_do_not_serve_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            secret = Path(temporary) / "secret.txt"
            secret.write_text("private sentinel", encoding="utf-8")
            paths = (
                "/README.md",
                "/.git/config",
                "/api/unknown",
                "/api/profile/",
                "/api/../profile",
                "/../../etc/passwd",
                "/%2e%2e/%2e%2e/etc/passwd",
                str(secret),
            )
            with patch.object(studio.kit, "profile_tokens") as profile:
                for path in paths:
                    with self.subTest(path=path):
                        status, headers, body = self.request(path=path)
                        self.assertEqual(status, 404)
                        self.assertEqual(json.loads(body), {"error": "Not found"})
                        self.assertNotIn(b"private sentinel", body)
                        self.assertTrue(headers["Content-Type"].startswith("application/json"))
            profile.assert_not_called()

    def test_frontend_and_api_share_one_address(self):
        for path, content_type in (
            ("/", "text/html"),
            ("/index.html", "text/html"),
            ("/assets/app-123.js", "text/javascript"),
            ("/assets/app-123.css?v=1", "text/css"),
            ("/favicon.svg", "image/svg+xml"),
            ("/THIRD_PARTY_NOTICES.txt", "text/plain"),
        ):
            with self.subTest(path=path):
                status, headers, body = self.request(path=path)
                self.assertEqual(status, 200)
                self.assertTrue(headers["Content-Type"].startswith(content_type))
                self.assertEqual(int(headers["Content-Length"]), len(body))
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertIn("connect-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(self.request()[0], 200)

    def test_missing_frontend_and_assets_keep_api_available(self):
        (self.frontend / "index.html").unlink()
        status, _, body = self.request(path="/")
        self.assertEqual(status, 503)
        self.assertIn("docs/studio.md", json.loads(body)["error"])
        self.assertEqual(self.request(path="/assets/missing.js")[0], 404)
        self.assertEqual(self.request()[0], 200)

    def test_no_directory_listing_spa_fallback_or_extra_files(self):
        (self.frontend / "README.md").write_text("not public", encoding="utf-8")
        (self.frontend / "assets/app.js.map").write_text("source map", encoding="utf-8")
        (self.frontend / "assets/config.json").write_text("{}", encoding="utf-8")
        for path in (
            "/assets",
            "/assets/",
            "/assets/app.js.map",
            "/assets/config.json",
            "/README.md",
            "/skills",
            "/src/App.tsx",
            "/node_modules/react/index.js",
            "/apps/studio/static/index.html",
            "/unknown",
            "/api/missing",
        ):
            with self.subTest(path=path):
                status, _, body = self.request(path=path)
                self.assertEqual(status, 404)
                self.assertEqual(json.loads(body), {"error": "Not found"})

    def test_encoded_traversal_and_windows_paths_are_rejected(self):
        paths = (
            "/assets/../index.html",
            "/assets/%2e%2e/index.html",
            "/assets/%2e%2e%2findex.html",
            "/assets/%252e%252e%252findex.html",
            "/assets/%5c..%5cREADME.md",
            "/assets/C:%5cWindows%5cfile.js",
            "/assets/%00.js",
            "/assets/%ff.js",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.request(path=path)[0], 404)

    def test_symlink_files_directories_and_frontend_root_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            outside = Path(temporary).resolve()
            (outside / "secret.js").write_text("private sentinel", encoding="utf-8")
            (self.frontend / "assets/leak.js").symlink_to(outside / "secret.js")
            self.assertEqual(self.request(path="/assets/leak.js")[0], 404)
            self.server.frontend_dir = outside / "linked"
            self.server.frontend_dir.symlink_to(self.frontend, target_is_directory=True)
            self.assertEqual(self.request(path="/")[0], 404)
            self.server.frontend_dir = self.frontend
            (self.frontend / "assets/linked").symlink_to(outside, target_is_directory=True)
            self.assertEqual(self.request(path="/assets/linked/secret.js")[0], 404)
            assets = self.frontend / "assets"
            assets.rename(self.frontend / "original-assets")
            assets.symlink_to(outside, target_is_directory=True)
            self.assertEqual(self.request(path="/assets/secret.js")[0], 404)

    def test_static_read_failure_is_safe(self):
        with patch.object(studio, "_frontend_bytes", side_effect=PermissionError("private path")):
            status, _, body = self.request(path="/")
        self.assertEqual(status, 500)
        self.assertEqual(json.loads(body), {"error": "Unable to read frontend asset"})

    def test_shipped_build_references_available_local_assets(self):
        self.server.frontend_dir = studio.FRONTEND
        status, _, body = self.request(path="/")
        self.assertEqual(status, 200)
        html = body.decode()
        self.assertNotIn("/src/main.tsx", html)
        references = re.findall(r'(?:src|href)="(/[^\"]+)"', html)
        self.assertTrue(any(path.endswith(".js") for path in references))
        self.assertTrue(any(path.endswith(".css") for path in references))
        for path in references:
            with self.subTest(path=path):
                self.assertEqual(self.request(path=path)[0], 200)

    def test_unsupported_methods_never_execute_actions(self):
        with (
            patch.object(studio.kit, "profile_tokens") as profile,
            patch.object(studio.kit, "sync_providers") as sync,
            patch.object(studio.kit, "install") as install,
            patch.object(studio.kit, "atomic_write") as write,
        ):
            for method in (
                "POST",
                "PUT",
                "PATCH",
                "DELETE",
                "OPTIONS",
                "TRACE",
                "CONNECT",
                "CUSTOM",
            ):
                for path in ("/api/profile", "/api/sync", "/README.md"):
                    with self.subTest(method=method, path=path):
                        status, headers, body = self.request(method, path, body=b"ignored")
                        self.assertEqual(status, 405)
                        self.assertEqual(headers["Allow"], "GET")
                        self.assertEqual(json.loads(body), {"error": "Method not allowed"})
            for action in (profile, sync, install, write):
                action.assert_not_called()

    def test_head_has_no_body_and_does_not_profile(self):
        with patch.object(studio.kit, "profile_tokens") as profile:
            status, headers, body = self.request("HEAD", "/api/profile")
        self.assertEqual(status, 405)
        self.assertEqual(headers["Allow"], "GET")
        self.assertEqual(body, b"")
        profile.assert_not_called()

    def test_query_parameters_cannot_select_files_or_actions(self):
        with (
            patch.object(studio.kit, "profile_tokens", return_value={"original": True}) as profile,
            patch.object(studio.kit, "sync_providers") as sync,
        ):
            status, _, body = self.request(path="/api/profile?root=/etc&action=sync&target=unknown")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"original": True})
        profile.assert_called_once_with()
        sync.assert_not_called()

    def test_absolute_and_malformed_request_targets_are_rejected(self):
        for path in (
            "http://example.com/api/profile",
            "http://[invalid/api/profile",
            "/api/profile#fragment",
        ):
            with self.subTest(path=path), patch.object(studio.kit, "profile_tokens") as profile:
                status, _, body = self.request(path=path)
                self.assertEqual(status, 400)
                self.assertIn("error", json.loads(body))
                profile.assert_not_called()

    def test_server_binds_loopback(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_host_validation_accepts_only_local_authorities(self):
        port = self.server.server_address[1]
        allowed = ("127.0.0.1", "localhost", f"127.0.0.1:{port}", f"LOCALHOST:{port}")
        rejected = (
            "evil.example",
            f"evil.example:{port}",
            "localhost.evil.example",
            "127.0.0.1.evil.example",
            f"localhost:{(port + 1) % 65536}",
            "user@localhost",
            "localhost,evil.example",
            "[::1]",
            "localhost.",
        )
        cases = [([host], 200) for host in allowed] + [([host], 403) for host in rejected]
        cases += [
            ([], 403),
            (["localhost", "evil.example"], 403),
            (["localhost", "localhost"], 403),
        ]
        with patch.object(studio.kit, "profile_tokens") as profile:
            for hosts, expected in cases:
                with self.subTest(hosts=hosts):
                    connection = HTTPConnection(*self.server.server_address, timeout=5)
                    try:
                        connection.putrequest("GET", "/api/health", skip_host=True)
                        for host in hosts:
                            connection.putheader("Host", host)
                        connection.putheader("X-Forwarded-Host", "localhost")
                        connection.endheaders()
                        response = connection.getresponse()
                        self.assertEqual(response.status, expected)
                        self.assertIn(
                            "status" if expected == 200 else "error", json.loads(response.read())
                        )
                    finally:
                        connection.close()
            profile.assert_not_called()

    def test_rebinding_host_is_rejected_before_profile_or_method_dispatch(self):
        with patch.object(studio.kit, "profile_tokens") as profile:
            for method in ("GET", "POST"):
                connection = HTTPConnection(*self.server.server_address, timeout=5)
                try:
                    connection.request(method, "/api/profile", headers={"Host": "attacker.example"})
                    response = connection.getresponse()
                    self.assertEqual(response.status, 403)
                    response.read()
                finally:
                    connection.close()
            profile.assert_not_called()


class StudioStartupTests(unittest.TestCase):
    def test_kit_studio_dispatch_and_scoped_bytecode_policy(self):
        for arguments, port, open_browser in (
            (["studio"], 8765, True),
            (["studio", "--port", "9000", "--no-browser"], 9000, False),
        ):
            with self.subTest(arguments=arguments), patch.object(sys, "dont_write_bytecode", False):

                def run(*args, **kwargs):
                    self.assertTrue(sys.dont_write_bytecode)
                    return 7

                with patch.object(studio, "main", side_effect=run) as launch:
                    self.assertEqual(studio.kit.main(arguments), 7)
                launch.assert_called_once_with(
                    ["--port", str(port)], open_browser=open_browser, require_frontend=True
                )
                self.assertFalse(sys.dont_write_bytecode)

    def test_missing_assets_fail_cli_without_binding_or_opening_browser(self):
        with (
            patch.object(studio, "_frontend_bytes", side_effect=FileNotFoundError),
            patch.object(studio, "create_server") as create,
            patch.object(studio.webbrowser, "open") as browser,
            patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            self.assertEqual(studio.kit.main(["studio"]), 1)
        create.assert_not_called()
        browser.assert_not_called()
        self.assertIn("docs/studio.md", stderr.getvalue())

    def test_browser_failure_leaves_manual_url(self):
        for result in (False, OSError("no browser")):
            with (
                self.subTest(result=result),
                patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                with patch.object(
                    studio.webbrowser,
                    "open",
                    side_effect=result if isinstance(result, Exception) else None,
                    return_value=False,
                ):
                    studio._open_browser("http://127.0.0.1:8765")
                self.assertIn("http://127.0.0.1:8765", stderr.getvalue())

    def test_browser_is_scheduled_after_server_is_listening(self):
        server = Mock()
        server.server_address = ("127.0.0.1", 9000)
        server.serve_forever.side_effect = KeyboardInterrupt
        context = Mock(__enter__=Mock(return_value=server), __exit__=Mock(return_value=False))
        with (
            patch.object(studio, "create_server", return_value=context),
            patch.object(studio.threading, "Thread") as thread,
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            self.assertEqual(studio.main(["--port", "9000"], open_browser=True), 0)
        thread.assert_called_once_with(
            target=studio._open_browser, args=("http://127.0.0.1:9000",), daemon=True
        )
        thread.return_value.start.assert_called_once_with()

    def test_kit_command_serves_production_assets_without_node_on_path(self):
        root = Path(__file__).resolve().parents[1]
        process = subprocess.Popen(
            [
                sys.executable,
                "-B",
                str(root / "tools/kit.py"),
                "studio",
                "--no-browser",
                "--port",
                "0",
            ],
            cwd=root,
            env={**os.environ, "PATH": ""},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        def stop():
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            process.stdout.close()
            process.stderr.close()

        self.addCleanup(stop)
        lines = queue.Queue()
        reader = threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True)
        reader.start()
        line = lines.get(timeout=10)
        match = re.search(r"http://127\.0\.0\.1:(\d+)", line)
        self.assertIsNotNone(match, line)
        connection = HTTPConnection("127.0.0.1", int(match[1]), timeout=5)
        try:
            for path, expected in (("/", 200), ("/api/health", 200), ("/tools/kit.py", 404)):
                connection.request("GET", path)
                response = connection.getresponse()
                self.assertEqual(response.status, expected)
                response.read()
        finally:
            connection.close()

    def test_import_preserves_bytecode_policy(self):
        root = Path(__file__).resolve().parents[1]
        script = (
            "import importlib, sys; "
            "sys.dont_write_bytecode = False; "
            "importlib.import_module('tools.studio_server'); "
            "assert sys.dont_write_bytecode is False"
        )
        # Isolate interpreter-global state from other tests and their imports.
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=root, capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_default_address_and_handler(self):
        with patch.object(studio, "ThreadingHTTPServer") as server:
            self.assertIs(studio.create_server(), server.return_value)
        server.assert_called_once_with(("127.0.0.1", 8765), studio.StudioHandler)

    def test_main_closes_server_on_keyboard_interrupt(self):
        server = Mock()
        server.server_address = ("127.0.0.1", 8765)
        server.serve_forever.side_effect = KeyboardInterrupt
        context = Mock()
        context.__enter__ = Mock(return_value=server)
        context.__exit__ = Mock(return_value=False)
        with (
            patch.object(studio, "create_server", return_value=context) as create,
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            self.assertEqual(studio.main([]), 0)
        create.assert_called_once_with(8765)
        context.__exit__.assert_called_once()
        self.assertIn("http://127.0.0.1:8765", stdout.getvalue())

    def test_bind_failure_is_reported_without_traceback(self):
        with (
            patch.object(studio, "create_server", side_effect=OSError("Address already in use")),
            patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            self.assertEqual(studio.main([]), 1)
        self.assertIn("Address already in use", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_invalid_port_is_rejected_before_binding(self):
        for port in ("-1", "65536", "invalid"):
            with (
                self.subTest(port=port),
                patch.object(studio, "create_server") as create,
                patch("sys.stderr", new_callable=io.StringIO),
                self.assertRaises(SystemExit),
            ):
                studio.main(["--port", port])
            create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
