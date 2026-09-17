import contextlib
import copy
import http.client
import importlib.util
import io
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import skill_watch as sw  # noqa: E402
import watch_fetch as wf  # noqa: E402

spec = importlib.util.spec_from_file_location("watch_demo", ROOT / "examples/skill-watch/run.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


def http_response(data, kind="text/html", status=200, headers=None):
    metadata = {"Content-Type": kind, **(headers or {})}
    head = f"HTTP/1.1 {status} Test\r\n"
    head += "".join(f"{key}: {value}\r\n" for key, value in metadata.items())
    sock = Mock()
    sock.makefile.return_value = io.BytesIO(head.encode("ascii") + b"\r\n" + data)
    response = http.client.HTTPResponse(sock)
    response.begin()
    return response


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        demo.prepare(self.root)
        self.watch = sw.Watch(self.root)

    def changed(self):
        (self.root / "training.html").write_text((demo.HERE / "after.html").read_text())

    def test_demo_covers_change_review_and_accept(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(demo.exercise(Path(directory))["verified"])

    def test_discovery_is_read_only_and_has_owner_line(self):
        with patch.object(wf, "fetch", side_effect=AssertionError("must not fetch")):
            result = sw.discover(self.root)
        self.assertEqual(
            result["references"][0]["owners"],
            [{"path": "skills/mkl-training-demo/SKILL.md", "line": 1}],
        )
        self.assertFalse(self.watch.state.exists())

    def test_missing_baseline_is_review_signal_without_side_effect(self):
        result = self.watch.check()
        self.assertEqual(result["status"], "review-needed")
        self.assertEqual(result["sources"][0]["status"], "new-source")
        self.assertFalse(self.watch.state.parent.exists())

    def test_unchanged_content_and_template_noise_stay_unchanged(self):
        self.watch.snapshot()
        path = self.root / "training.html"
        path.write_text(path.read_text().replace("News 1", "News 999").replace("Monday", "Friday"))
        self.assertEqual(self.watch.check()["status"], "unchanged")

    def test_repeated_checks_preserve_baseline_bytes_and_mtime(self):
        self.watch.snapshot()
        before, mtime = self.watch.state.read_bytes(), self.watch.state.stat().st_mtime_ns
        self.changed()
        for _ in range(2):
            result = self.watch.check()
            self.assertEqual(result["status"], "review-needed")
            self.assertIn(
                "-Checkpoints remain enabled during this diagnostic.\n+Checkpoints are disabled",
                result["sources"][0]["diff"],
            )
        self.assertEqual(self.watch.state.read_bytes(), before)
        self.assertEqual(self.watch.state.stat().st_mtime_ns, mtime)

    def test_impact_follows_agent_dependency_and_existing_exports(self):
        for provider, (skill_dir, agent_dir, extension) in sw.PROVIDERS.items():
            skill_suffix = (
                "mkl-training-demo.md" if provider == "grok-bot" else "mkl-training-demo/SKILL.md"
            )
            for path in (
                f"providers/{provider}/{skill_dir}/{skill_suffix}",
                f"providers/{provider}/{agent_dir}/mkl-demo-investigator{extension}",
            ):
                output = self.root / path
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("generated fixture")
        result = self.watch.check()["sources"][0]
        self.assertEqual(result["agents"], ["agents/mkl-demo-investigator.toml"])
        self.assertEqual(len(result["generated_files"]), 10)

    def test_snapshot_refuses_overwrite(self):
        self.watch.snapshot()
        before = self.watch.state.read_bytes()
        self.changed()
        with self.assertRaises(sw.WatchError):
            self.watch.snapshot()
        self.assertEqual(self.watch.state.read_bytes(), before)

    def test_snapshot_failure_does_not_create_partial_baseline(self):
        self.watch.sources["missing"] = {
            "id": "missing",
            "file": "absent.txt",
            "owners": ["skills/mkl-training-demo/SKILL.md"],
        }
        with self.assertRaises(sw.WatchError):
            self.watch.snapshot()
        self.assertFalse(self.watch.state.exists())

    def test_incomplete_response_cannot_create_partial_baseline(self):
        source = {**self.watch.sources["training"], "id": "incomplete"}
        source.pop("file")
        source["url"] = "https://example.org/docs"
        self.watch.sources["incomplete"] = source
        content = (demo.HERE / "before.html").read_bytes()
        with patch.object(wf, "PublicHTTPS") as connection:
            connection.return_value.getresponse.return_value = http_response(
                content, headers={"Content-Length": len(content) + 100}
            )
            with self.assertRaises(sw.WatchError):
                self.watch.snapshot()
        self.assertFalse(self.watch.state.parent.exists())

    def test_incomplete_response_is_error_and_cannot_replace_baseline(self):
        self.watch.sources["training"].pop("file")
        self.watch.sources["training"]["url"] = "https://example.org/docs"
        content = (demo.HERE / "before.html").read_bytes()
        with patch.object(wf, "PublicHTTPS") as connection:
            connection.return_value.getresponse.return_value = http_response(
                content, headers={"Content-Length": len(content)}
            )
            self.watch.snapshot()
            before = self.watch.state.read_bytes()
            mtime = self.watch.state.stat().st_mtime_ns
            baseline, _ = self.watch.baseline()
            expected = baseline["sources"]["training"]["sha256"]
            # Every selected marker still exists in this incomplete response.
            connection.return_value.getresponse.side_effect = lambda: http_response(
                content, headers={"Content-Length": len(content) + 100}
            )
            result = self.watch.check()
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["sources"][0]["status"], "error")
            with self.assertRaises(sw.WatchError):
                self.watch.accept("training", expected)
        self.assertEqual(self.watch.state.read_bytes(), before)
        self.assertEqual(self.watch.state.stat().st_mtime_ns, mtime)

    def test_accept_requires_current_reviewed_hash_and_preserves_other_entries(self):
        self.watch.snapshot()
        initial, _ = self.watch.baseline()
        self.changed()
        with self.assertRaises(sw.WatchError):
            self.watch.accept("training", initial["sources"]["training"]["sha256"])
        self.assertEqual(self.watch.baseline()[0], initial)
        self.watch.sources["second"] = {**self.watch.sources["training"], "id": "second"}
        current = self.watch.capture("second")
        self.watch.accept("second", current["sha256"])
        self.assertEqual(
            self.watch.baseline()[0]["sources"]["training"], initial["sources"]["training"]
        )
        self.watch.accept("training", current["sha256"])
        self.assertEqual(self.watch.check()["status"], "unchanged")

    def test_changed_selection_is_not_an_unchanged_source(self):
        self.watch.snapshot()
        self.watch.sources["training"]["start"] = "Use smoke_run"
        self.assertEqual(self.watch.check()["sources"][0]["status"], "configuration-changed")

    def test_redirect_change_is_visible_even_if_text_matches(self):
        self.watch.sources["training"].pop("file")
        self.watch.sources["training"]["url"] = "https://example.org/docs"
        content = (demo.HERE / "before.html").read_text()
        with patch.object(
            sw, "fetch", return_value=(content, "text/html", "https://example.org/v1")
        ):
            self.watch.snapshot()
        with patch.object(
            sw, "fetch", return_value=(content, "text/html", "https://example.org/v2")
        ):
            self.assertEqual(self.watch.check()["sources"][0]["status"], "redirect-changed")

    def test_missing_or_ambiguous_markers_are_errors_and_preserve_baseline(self):
        self.watch.snapshot()
        before = self.watch.state.read_bytes()
        for text in ("unrelated page", "One-batch smoke test One-batch smoke test Full training"):
            (self.root / "training.html").write_text(text)
            self.assertEqual(self.watch.check()["status"], "error")
        self.assertEqual(self.watch.state.read_bytes(), before)

    def test_tampered_baseline_is_rejected(self):
        self.watch.snapshot()
        state, _ = self.watch.baseline()
        state["sources"]["training"]["text"] = "changed without matching hash"
        self.watch.state.write_text(json.dumps(state))
        with self.assertRaises(sw.WatchError):
            self.watch.check()

    def test_concurrent_state_change_prevents_overwrite(self):
        self.watch.snapshot()
        state, raw = self.watch.baseline()
        newer = copy.deepcopy(state)
        newer["sources"]["training"]["captured_at"] = "another writer"
        self.watch.save(newer, raw)
        with self.assertRaises(sw.WatchError):
            self.watch.save(state, raw)
        self.assertEqual(self.watch.baseline()[0], newer)

    def test_accumulated_source_history_cannot_write_an_unreadable_baseline(self):
        self.watch.snapshot()
        state, raw = self.watch.baseline()
        entry = copy.deepcopy(state["sources"]["training"])
        entry["text"] = "😀" * wf.MAX_TEXT
        entry["sha256"] = sw.digest(entry["text"])
        # Removed sources remain in the baseline across configuration changes.
        state["sources"].update({f"retired-{index}": entry for index in range(26)})
        before = self.watch.state.read_bytes()
        mtime = self.watch.state.stat().st_mtime_ns
        with self.assertRaisesRegex(sw.WatchError, "Baseline exceeds"):
            self.watch.save(state, raw)
        self.assertEqual(self.watch.state.read_bytes(), before)
        self.assertEqual(self.watch.state.stat().st_mtime_ns, mtime)
        self.assertEqual(self.watch.check()["status"], "unchanged")
        self.assertEqual(list(self.watch.state.parent.iterdir()), [self.watch.state])

    def test_oversized_snapshot_and_accept_preserve_state(self):
        with patch.object(sw, "MAX_BASELINE_BYTES", 1):
            with self.assertRaisesRegex(sw.WatchError, "Baseline exceeds"):
                self.watch.snapshot()
        self.assertFalse(self.watch.state.parent.exists())
        self.watch.snapshot()
        before = self.watch.state.read_bytes()
        mtime = self.watch.state.stat().st_mtime_ns
        self.changed()
        self.watch.sources["second"] = {**self.watch.sources["training"], "id": "second"}
        current = self.watch.capture("second")
        with patch.object(sw, "MAX_BASELINE_BYTES", len(before)):
            with self.assertRaisesRegex(sw.WatchError, "Baseline exceeds"):
                self.watch.accept("second", current["sha256"])
        self.assertEqual(self.watch.state.read_bytes(), before)
        self.assertEqual(self.watch.state.stat().st_mtime_ns, mtime)
        self.assertEqual(list(self.watch.state.parent.iterdir()), [self.watch.state])

    def test_baseline_limit_counts_utf8_bytes_including_json_and_newline(self):
        entry = self.watch.capture("training")
        entry["text"] = 'Zażółć 😀 "quoted"'
        entry["sha256"] = sw.digest(entry["text"])
        state = {"version": 1, "sources": {"training": entry}}
        serialized = json.dumps(state, indent=2, ensure_ascii=False) + "\n"
        encoded = serialized.encode("utf-8")
        self.assertGreater(len(encoded), len(serialized))
        with patch.object(sw, "MAX_BASELINE_BYTES", len(encoded) - 1):
            with self.assertRaisesRegex(sw.WatchError, "Baseline exceeds"):
                self.watch.save(state, None)
        self.assertFalse(self.watch.state.parent.exists())
        with patch.object(sw, "MAX_BASELINE_BYTES", len(encoded)):
            self.watch.save(state, None)
            self.assertEqual(self.watch.baseline()[0], state)
        self.assertEqual(self.watch.state.read_bytes(), encoded)

    def test_paths_cannot_escape_project_or_follow_symlinks(self):
        for path in ("../outside", "/tmp/outside", ".git/config"):
            with self.subTest(path=path), self.assertRaises(sw.WatchError):
                sw.local_path(self.root, path)
        with tempfile.TemporaryDirectory() as outside:
            (self.root / "escape").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(sw.WatchError):
                sw.local_path(self.root, "escape/new/file")
            (self.root / ".skill-watch").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(sw.WatchError):
                self.watch.snapshot()
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_cli_exit_codes_distinguish_review_and_execution_error(self):
        command = ["--project", str(self.root)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sw.main([*command, "check"]), 1)
            self.assertEqual(sw.main([*command, "snapshot"]), 0)
            self.assertEqual(sw.main([*command, "check"]), 0)
            (self.root / "training.html").unlink()
            self.assertEqual(sw.main([*command, "check"]), 2)


class RetrievalTests(unittest.TestCase):
    def test_markup_filter_preserves_code_indentation_and_plain_text(self):
        content = "<header>noise</header><h2>Start</h2><p>A <b>bold</b> claim.</p><pre>if x:\n    y()</pre><script>ignore me</script><h2>End</h2>"
        text = wf.select_text(content, "text/html", "Start", "End")
        self.assertIn("A bold claim.", text)
        self.assertIn("if x:\n    y()", text)
        self.assertNotIn("noise", text)
        self.assertNotIn("ignore me", text)

    def test_ambiguous_missing_and_oversized_selections_fail(self):
        for content, start, end in (
            ("a a b", "a", "b"),
            ("a c", "a", "b"),
            ("", "", ""),
            ("x" * (wf.MAX_TEXT + 1), "", ""),
        ):
            with self.subTest(start=start), self.assertRaises(wf.WatchError):
                wf.select_text(content, "text/plain", start, end)

    def test_only_credential_free_https_on_standard_port(self):
        for url in (
            "http://example.org",
            "file:///etc/passwd",
            "https://user:pass@example.org",
            "https://example.org:8443/",
            "https://example.org/\nsecret",
        ):
            with self.subTest(url=url), self.assertRaises(wf.WatchError):
                wf.validate_url(url)

    def test_private_dns_results_never_connect(self):
        for address in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1"):
            records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]
            with (
                self.subTest(address=address),
                patch.object(socket, "getaddrinfo", return_value=records),
                patch.object(socket, "create_connection") as connect,
            ):
                with self.assertRaises(wf.WatchError):
                    wf.PublicHTTPS("example.org").connect()
                connect.assert_not_called()

    def test_mixed_dns_skips_non_public_addresses(self):
        records = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fe80::1", 443, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        ]
        connection = wf.PublicHTTPS("example.org", timeout=5)
        connection._context = Mock()
        with (
            patch.object(socket, "getaddrinfo", return_value=records) as resolve,
            patch.object(socket, "create_connection") as connect,
            patch.object(wf.time, "monotonic", return_value=100.0),
        ):
            connection.connect()
        resolve.assert_called_once_with("example.org", 443, type=socket.SOCK_STREAM)
        connect.assert_called_once_with(("93.184.216.34", 443), timeout=5)
        connection._context.wrap_socket.assert_called_once_with(
            connect.return_value, server_hostname="example.org"
        )

    def test_dns_result_is_pinned_while_tls_uses_original_hostname(self):
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        connection = wf.PublicHTTPS("example.org", timeout=5)
        connection._context = Mock()
        with (
            patch.object(socket, "getaddrinfo", return_value=records),
            patch.object(socket, "create_connection") as connect,
            patch.object(wf.time, "monotonic", return_value=100.0),
        ):
            connection.connect()
        connect.assert_called_once_with(("93.184.216.34", 443), timeout=5)
        connection._context.wrap_socket.assert_called_once_with(
            connect.return_value, server_hostname="example.org"
        )

    def test_unreachable_public_address_falls_back_without_redoing_dns(self):
        records = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.35", 443)),
        ]
        connection = wf.PublicHTTPS("example.org", timeout=5)
        connection._context = Mock()
        second_socket = Mock()
        with (
            patch.object(socket, "getaddrinfo", return_value=records) as resolve,
            patch.object(
                socket,
                "create_connection",
                side_effect=[OSError("first address is unreachable"), second_socket],
            ) as connect,
            patch.object(wf.time, "monotonic", return_value=100.0),
        ):
            connection.connect()
        resolve.assert_called_once_with("example.org", 443, type=socket.SOCK_STREAM)
        self.assertEqual(connect.call_count, 2)
        connect.assert_any_call(("93.184.216.34", 443), timeout=5)
        connect.assert_any_call(("93.184.216.35", 443), timeout=5)
        connection._context.wrap_socket.assert_called_once_with(
            second_socket, server_hostname="example.org"
        )

    def test_address_fallbacks_share_one_connection_timeout_budget(self):
        records = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.35", 443)),
        ]
        connection = wf.PublicHTTPS("example.org", timeout=5)
        connection._context = Mock()
        with (
            patch.object(socket, "getaddrinfo", return_value=records),
            patch.object(
                socket,
                "create_connection",
                side_effect=[OSError("first address is unreachable"), Mock()],
            ) as connect,
            patch.object(wf.time, "monotonic", side_effect=[100.0, 101.0, 104.5]),
        ):
            connection.connect()
        self.assertEqual(connect.call_count, 2)
        self.assertAlmostEqual(connect.call_args_list[0].kwargs["timeout"], 4.0)
        self.assertAlmostEqual(connect.call_args_list[1].kwargs["timeout"], 0.5)

    def test_expired_connection_budget_raises_without_connecting(self):
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        connection = wf.PublicHTTPS("example.org", timeout=5)
        connection._context = Mock()
        with (
            patch.object(socket, "getaddrinfo", return_value=records),
            patch.object(socket, "create_connection") as connect,
            patch.object(wf.time, "monotonic", side_effect=[100.0, 106.0]),
        ):
            with self.assertRaisesRegex(TimeoutError, "connection deadline exceeded"):
                connection.connect()
        connect.assert_not_called()

    def test_html_refresh_is_followed_without_executing_scripts(self):
        first = http_response(
            b'<meta http-equiv="refresh" content="0; url=/v2/docs"><script>bad()</script>'
        )
        second = http_response(b"<p>real docs</p>")
        with patch.object(wf, "PublicHTTPS") as connection:
            connection.return_value.getresponse.side_effect = [first, second]
            text, _, resolved = wf.fetch("https://example.org/stable")
        self.assertEqual(resolved, "https://example.org/v2/docs")
        self.assertEqual(text, "<p>real docs</p>")
        self.assertEqual(connection.call_count, 2)

    def test_redirect_downgrade_oversize_and_http_errors_fail(self):
        responses = [
            http_response(b"", status=302, headers={"Location": "http://example.org"}),
            http_response(b"x" * (wf.MAX_BYTES + 1)),
            http_response(b"unavailable", status=503),
        ]
        for response in responses:
            with (
                self.subTest(status=response.status),
                patch.object(wf, "PublicHTTPS") as connection,
            ):
                connection.return_value.getresponse.return_value = response
                with self.assertRaises(wf.WatchError):
                    wf.fetch("https://example.org")

    def test_complete_http_framing_is_supported(self):
        cases = (
            (b"docs", {"Content-Length": 4}),
            (b"2\r\ndo\r\n2\r\ncs\r\n0\r\n\r\n", {"Transfer-Encoding": "chunked"}),
            (b"docs", {"Connection": "close"}),
        )
        for body, headers in cases:
            with self.subTest(headers=headers), patch.object(wf, "PublicHTTPS") as connection:
                connection.return_value.getresponse.return_value = http_response(
                    body, kind="text/plain", headers=headers
                )
                self.assertEqual(wf.fetch("https://example.org/docs")[0], "docs")

    def test_incomplete_http_bodies_are_errors(self):
        cases = (
            (b"complete selected paragraph", {"Content-Length": 100}),
            (b"", {"Content-Length": 1}),
            (b"4\r\ndo", {"Transfer-Encoding": "chunked"}),
            (b"4\r\ndocs\r\n", {"Transfer-Encoding": "chunked"}),
        )
        for body, headers in cases:
            with self.subTest(body=body), patch.object(wf, "PublicHTTPS") as connection:
                connection.return_value.getresponse.return_value = http_response(
                    body, kind="text/plain", headers=headers
                )
                with self.assertRaises(wf.WatchError):
                    wf.fetch("https://example.org/docs")
                connection.return_value.close.assert_called_once_with()

    def test_socket_timeout_is_not_a_valid_empty_source(self):
        with patch.object(wf, "PublicHTTPS") as connection:
            connection.return_value.request.side_effect = TimeoutError()
            with self.assertRaises(wf.WatchError):
                wf.fetch("https://example.org")


if __name__ == "__main__":
    unittest.main()
