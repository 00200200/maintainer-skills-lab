#!/usr/bin/env python3
"""Read-only library overview until an explicit sync action is requested."""

from __future__ import annotations

import contextlib
import io
import sys
import textwrap
import time

# Launching this tool must not create bytecode caches in the repository.
sys.dont_write_bytecode = True

if __package__:
    from . import kit
else:
    import kit

try:
    import curses
except ImportError:
    curses = None


class Dashboard:
    """Keep data and action handling independent of the terminal."""

    def __init__(self):
        self.skills = {}
        self.agents = {}
        self.profile = None
        self.error = ""
        self.output = ["No actions yet. Press s, c or t."]
        self.view = "library"
        self.offsets = {"library": 0, "output": 0}

    def refresh(self):
        try:
            skills, agents = kit.load_library()
            profile = kit.profile_tokens(sort_by="name")
        except Exception as exc:
            self.error = f"Refresh failed: {exc}"
            return
        self.skills, self.agents, self.profile = skills, agents, profile
        self.error = ""

    def run_action(self, key):
        if key not in ("s", "c", "t"):
            return
        name = {"s": "sync", "c": "check", "t": "tokens"}[key]
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                if key == "t":
                    profile = kit.profile_tokens(sort_by="name")
                    print(kit.format_tokens_table(profile))
                    self.profile = profile
                    code = 0
                else:
                    code = kit.main([name])
            status = f"{name}: {'OK' if code == 0 else f'FAILED (exit {code})'}"
        except Exception as exc:
            status = f"{name}: ERROR: {exc}"
        self.output = [status, *captured.getvalue().splitlines()]
        self.view = "output"
        self.offsets["output"] = 0
        self.refresh()

    def library_lines(self):
        lines = [f"Skills: {len(self.skills)} | Agents: {len(self.agents)}"]
        if self.error:
            lines.extend([self.error, "Data below may be stale; refresh is retried automatically."])
        if self.profile is None:
            return lines + ["Token profile unavailable."]
        profile = self.profile
        summary = profile["summary"]
        lines.extend(
            [
                f"Tokens: {summary['skills_total_tokens']} | "
                f"Names: {summary['names_only_floor_tokens']} | "
                f"Descriptions: {summary['descriptions_ceiling_tokens']}",
                f"Encoding: {profile['encoding']}",
                "",
                "SKILLS (total / body / description tokens; warnings)",
            ]
        )
        for skill in profile["skills"]:
            warnings = "; ".join(skill["warnings"]) or "OK"
            lines.append(
                f"{skill['name']}: {skill['tokens']} / {skill['body_tokens']} / "
                f"{skill['desc_tokens']}  {warnings}"
            )
        lines.extend(["", "AGENTS (instructions / referenced skills / total tokens)"])
        for agent in profile["agents"]:
            lines.append(
                f"{agent['name']} [{agent['mode']}]: {agent['instructions_tokens']} / "
                f"{agent['referenced_skills_tokens']} / {agent['total_tokens']} "
                f"({agent['referenced_skills_count']} skills)"
            )
        lines.extend(["", "AVAILABLE PROVIDERS (export files / tokens)"])
        for target in kit.EXPORT_TARGETS:
            label = kit.PROVIDER_LABELS.get(target, target)
            data = profile["targets"].get(target)
            detail = (
                f"{data['files']} files / {data['total_tokens']} tokens" if data else "unavailable"
            )
            lines.append(f"{label} ({target}): {detail}")
        return lines

    def lines(self, width=None):
        lines = self.output if self.view == "output" else self.library_lines()
        if width is None:
            return lines
        return [part for line in lines for part in (textwrap.wrap(line, max(1, width)) or [""])]

    def scroll(self, amount, page_size, width=None):
        maximum = max(0, len(self.lines(width)) - page_size)
        self.offsets[self.view] = min(maximum, max(0, self.offsets[self.view] + amount))


def put_line(screen, row, text):
    """Clip writes, including during a resize and in very small terminals."""
    height, width = screen.getmaxyx()
    if not 0 <= row < height or width < 2:
        return
    # Source descriptions and command errors may contain control characters.
    text = "".join(char if char.isprintable() else " " for char in text)
    try:
        screen.addnstr(row, 0, text, width - 1)
    except curses.error:
        pass  # A resize can invalidate the dimensions between these calls.


def draw(screen, dashboard):
    screen.erase()
    height, width = screen.getmaxyx()
    content_width = max(1, width - 1)
    page_size = max(1, height - 3)
    dashboard.scroll(0, page_size, content_width)
    lines = dashboard.lines(content_width)
    offset = dashboard.offsets[dashboard.view]
    put_line(
        screen,
        0,
        f"Maintainer Skills Lab | {dashboard.view} | "
        f"{offset + 1}-{min(offset + page_size, len(lines))}/{len(lines)}",
    )
    for row, line in enumerate(lines[offset : offset + page_size], 1):
        if row < height - 2:
            put_line(screen, row, line)
    put_line(
        screen, height - 2, dashboard.error or "Auto-refresh: 5s | Tab: library / action results"
    )
    put_line(
        screen,
        height - 1,
        "s sync | c check | t tokens | q quit | Up/Down PgUp/PgDn Home/End scroll",
    )
    screen.refresh()
    return page_size


def run(screen):
    screen.keypad(True)
    screen.timeout(250)
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    dashboard = Dashboard()
    next_refresh = 0.0
    while True:
        if time.monotonic() >= next_refresh:
            dashboard.refresh()
            next_refresh = time.monotonic() + 5
        page_size = draw(screen, dashboard)
        content_width = max(1, screen.getmaxyx()[1] - 1)
        key = screen.getch()
        if key in (ord("q"), 3):
            return
        if key == ord("\t"):
            dashboard.view = "output" if dashboard.view == "library" else "library"
        elif key in (ord("s"), ord("c"), ord("t")):
            put_line(screen, 0, "Running action... (Ctrl+C to exit)")
            screen.refresh()
            dashboard.run_action(chr(key))
            next_refresh = time.monotonic() + 5
        elif key in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_PPAGE, curses.KEY_NPAGE):
            amount = {
                curses.KEY_UP: -1,
                curses.KEY_DOWN: 1,
                curses.KEY_PPAGE: -page_size,
                curses.KEY_NPAGE: page_size,
            }[key]
            dashboard.scroll(amount, page_size, content_width)
        elif key == curses.KEY_HOME:
            dashboard.offsets[dashboard.view] = 0
        elif key == curses.KEY_END:
            dashboard.scroll(len(dashboard.lines(content_width)), page_size, content_width)
        # KEY_RESIZE and timeout both redraw using fresh terminal dimensions.


def main():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(
            "Dashboard requires an interactive TTY; use tools/kit.py for CLI commands.",
            file=sys.stderr,
        )
        return 0
    if curses is None:
        print("Dashboard requires Python's standard curses module.", file=sys.stderr)
        return 1
    try:
        curses.wrapper(run)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"Dashboard error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
