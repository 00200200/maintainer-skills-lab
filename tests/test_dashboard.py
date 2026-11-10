import io
import unittest
from unittest.mock import Mock, patch

from tools import dashboard


def sample_profile():
    return {
        "encoding": "heuristic",
        "summary": {
            "skills_total_tokens": 120,
            "names_only_floor_tokens": 5,
            "descriptions_ceiling_tokens": 10,
        },
        "skills": [
            {
                "name": "mkl-example",
                "tokens": 120,
                "body_tokens": 100,
                "desc_tokens": 10,
                "warnings": ["desc > 5 tokens"],
            }
        ],
        "agents": [
            {
                "name": "mkl-agent",
                "mode": "full",
                "instructions_tokens": 20,
                "referenced_skills_tokens": 120,
                "total_tokens": 140,
                "referenced_skills_count": 1,
            }
        ],
        "targets": {"codex": {"files": 2, "total_tokens": 260}},
    }


class DashboardTests(unittest.TestCase):
    def test_noninteractive_exit_does_not_initialize_or_load(self):
        for stdin_tty, stdout_tty in ((False, False), (False, True), (True, False)):
            with (
                self.subTest(stdin=stdin_tty, stdout=stdout_tty),
                patch.object(dashboard.sys, "stdin") as stdin,
                patch.object(dashboard.sys, "stdout") as stdout,
                patch.object(dashboard.sys, "stderr", new_callable=io.StringIO) as stderr,
                patch.object(dashboard, "curses") as curses,
                patch.object(dashboard.kit, "load_library") as load,
                patch.object(dashboard.kit, "main") as command,
            ):
                stdin.isatty.return_value = stdin_tty
                stdout.isatty.return_value = stdout_tty
                self.assertEqual(dashboard.main(), 0)
                self.assertIn("interactive TTY", stderr.getvalue())
                curses.wrapper.assert_not_called()
                load.assert_not_called()
                command.assert_not_called()

    def test_refresh_uses_library_and_profiler_without_running_commands(self):
        state = dashboard.Dashboard()
        with (
            patch.object(
                dashboard.kit, "load_library", return_value=({"mkl-example": {}}, {"mkl-agent": {}})
            ) as load,
            patch.object(dashboard.kit, "profile_tokens", return_value=sample_profile()) as profile,
            patch.object(dashboard.kit, "main") as command,
            patch.object(dashboard.kit, "sync_providers") as sync,
        ):
            state.refresh()
        load.assert_called_once_with()
        profile.assert_called_once_with(sort_by="name")
        command.assert_not_called()
        sync.assert_not_called()
        text = "\n".join(state.library_lines())
        for expected in (
            "Skills: 1 | Agents: 1",
            "mkl-example",
            "mkl-agent",
            "desc > 5 tokens",
            "Tokens: 120",
            "Codex",
            "260 tokens",
        ):
            self.assertIn(expected, text)

    def test_sync_and_check_capture_output_and_exit_status(self):
        for key, command, code in (("s", "sync", 0), ("c", "check", 1)):
            with self.subTest(key=key):
                state = dashboard.Dashboard()

                def action(argv, *, code=code):
                    print("action details")
                    print("diagnostic", file=dashboard.sys.stderr)
                    return code

                with (
                    patch.object(dashboard.kit, "main", side_effect=action) as main,
                    patch.object(state, "refresh") as refresh,
                ):
                    state.run_action(key)
                main.assert_called_once_with([command])
                refresh.assert_called_once_with()
                self.assertEqual(state.view, "output")
                self.assertIn("OK" if code == 0 else "FAILED (exit 1)", state.output[0])
                self.assertEqual(state.output[1:], ["action details", "diagnostic"])

    def test_token_action_uses_existing_formatter(self):
        state = dashboard.Dashboard()
        profile = sample_profile()
        with (
            patch.object(dashboard.kit, "profile_tokens", return_value=profile) as profiler,
            patch.object(
                dashboard.kit, "format_tokens_table", return_value="token report"
            ) as formatter,
            patch.object(state, "refresh"),
            patch.object(dashboard.kit, "main") as command,
        ):
            state.run_action("t")
        profiler.assert_called_once_with(sort_by="name")
        formatter.assert_called_once_with(profile)
        command.assert_not_called()
        self.assertEqual(state.output, ["tokens: OK", "token report"])

    def test_action_exception_keeps_partial_output_and_restores_streams(self):
        state = dashboard.Dashboard()
        original_stdout, original_stderr = dashboard.sys.stdout, dashboard.sys.stderr

        def fail(argv):
            print("before failure")
            raise OSError("permission denied")

        with patch.object(dashboard.kit, "main", side_effect=fail), patch.object(state, "refresh"):
            state.run_action("s")
        self.assertIn("ERROR: permission denied", state.output[0])
        self.assertIn("before failure", state.output)
        self.assertIs(dashboard.sys.stdout, original_stdout)
        self.assertIs(dashboard.sys.stderr, original_stderr)

    def test_refresh_failure_is_visible_and_can_recover(self):
        state = dashboard.Dashboard()
        with patch.object(
            dashboard.kit, "load_library", side_effect=dashboard.kit.KitError("bad source")
        ):
            state.refresh()
        self.assertIn("bad source", "\n".join(state.library_lines()))
        with (
            patch.object(dashboard.kit, "load_library", return_value=({}, {})),
            patch.object(dashboard.kit, "profile_tokens", return_value=sample_profile()),
        ):
            state.refresh()
        self.assertEqual(state.error, "")
        with (
            patch.object(dashboard.kit, "load_library", return_value=({}, {})),
            patch.object(dashboard.kit, "profile_tokens", side_effect=ValueError("bad encoding")),
        ):
            state.refresh()
        self.assertIn("bad encoding", state.error)
        self.assertIsNotNone(state.profile)

    def test_unknown_action_does_nothing_and_interrupt_propagates(self):
        state = dashboard.Dashboard()
        with (
            patch.object(dashboard.kit, "main", side_effect=KeyboardInterrupt) as command,
            patch.object(state, "refresh") as refresh,
        ):
            state.run_action("x")
            command.assert_not_called()
            refresh.assert_not_called()
            with self.assertRaises(KeyboardInterrupt):
                state.run_action("c")

    def test_scrolling_clamps_and_preserves_each_view_offset(self):
        state = dashboard.Dashboard()
        state.view = "output"
        state.output = [str(i) for i in range(30)]
        state.scroll(100, 5)
        self.assertEqual(state.offsets["output"], 25)
        state.scroll(0, 20)  # Larger terminal reduces the maximum offset.
        self.assertEqual(state.offsets["output"], 10)
        state.view = "library"
        state.scroll(-100, 5)
        self.assertEqual(state.offsets["library"], 0)
        self.assertEqual(state.offsets["output"], 10)

    def test_long_action_errors_wrap_into_scrollable_lines(self):
        state = dashboard.Dashboard()
        state.view = "output"
        state.output = ["ERROR: " + "x" * 100]
        lines = state.lines(width=20)
        self.assertTrue(all(len(line) <= 20 for line in lines))
        self.assertEqual("".join(lines).replace(" ", ""), "ERROR:" + "x" * 100)
        state.scroll(100, 2, width=20)
        self.assertEqual(state.offsets["output"], len(lines) - 2)

    def test_terminal_interrupt_and_setup_error_exit_cleanly(self):
        for error, expected in ((KeyboardInterrupt(), 0), (RuntimeError("bad terminal"), 1)):
            with (
                self.subTest(error=type(error).__name__),
                patch.object(dashboard.sys, "stdin") as stdin,
                patch.object(dashboard.sys, "stdout") as stdout,
                patch.object(dashboard.sys, "stderr", new_callable=io.StringIO) as stderr,
                patch.object(dashboard, "curses") as curses,
            ):
                stdin.isatty.return_value = stdout.isatty.return_value = True
                curses.wrapper.side_effect = error
                self.assertEqual(dashboard.main(), expected)
                if expected:
                    self.assertIn("bad terminal", stderr.getvalue())

    def test_missing_curses_exits_with_message(self):
        with (
            patch.object(dashboard.sys, "stdin") as stdin,
            patch.object(dashboard.sys, "stdout") as stdout,
            patch.object(dashboard.sys, "stderr", new_callable=io.StringIO) as stderr,
            patch.object(dashboard, "curses", None),
        ):
            stdin.isatty.return_value = stdout.isatty.return_value = True
            self.assertEqual(dashboard.main(), 1)
            self.assertIn("curses", stderr.getvalue())

    @unittest.skipIf(dashboard.curses is None, "standard curses unavailable")
    def test_resize_tiny_terminal_scroll_and_quit(self):
        screen = Mock()
        screen.getmaxyx.side_effect = lambda: dimensions[0]
        dimensions = [(24, 80)]
        keys = iter(
            [
                dashboard.curses.KEY_END,
                dashboard.curses.KEY_RESIZE,
                dashboard.curses.KEY_DOWN,
                ord("\t"),
                ord("q"),
            ]
        )

        def getch():
            key = next(keys)
            if key == dashboard.curses.KEY_RESIZE:
                dimensions[0] = (2, 1)
            return key

        screen.getch.side_effect = getch
        with (
            patch.object(dashboard.Dashboard, "refresh") as refresh,
            patch.object(dashboard.curses, "curs_set"),
            patch.object(dashboard.time, "monotonic", return_value=0),
        ):
            dashboard.run(screen)
        refresh.assert_called_once_with()
        self.assertEqual(screen.refresh.call_count, 5)


if __name__ == "__main__":
    unittest.main()
