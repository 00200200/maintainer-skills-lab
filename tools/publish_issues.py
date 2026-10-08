#!/usr/bin/env python3
"""Publish contributor task drafts from docs/tasks/ to GitHub Issues using gh CLI."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS_DIR = ROOT / "docs" / "tasks"

LABEL_PATTERN = re.compile(r"\*\*Labels\*\*:\s*(.+)$")


def parse_issue(path: Path) -> dict[str, str | list[str]]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    title = ""
    labels: list[str] = []
    body_lines: list[str] = []

    for line in lines:
        if not title and line.startswith("# "):
            title = line.removeprefix("# ").strip()
            continue

        match = LABEL_PATTERN.search(line)
        if match and not labels:
            raw_labels = match.group(1).split(",")
            labels = [lbl.strip().strip("`").strip() for lbl in raw_labels if lbl.strip()]
            continue

        body_lines.append(line)

    body = "\n".join(body_lines).strip()
    return {
        "file": path.name,
        "title": title or path.stem,
        "labels": labels,
        "body": body,
    }


def ensure_labels(required_labels: set[str], dry_run: bool = True):
    existing = set()
    try:
        proc = subprocess.run(
            ["gh", "label", "list", "--json", "name", "--jq", ".[].name"],
            capture_output=True,
            text=True,
            check=True,
        )
        existing = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    except (subprocess.CalledProcessError, FileNotFoundError):
        return

    missing = required_labels - existing
    for label in sorted(missing):
        print(f"[*] Creating missing GitHub label: '{label}'")
        if not dry_run:
            subprocess.run(
                [
                    "gh",
                    "label",
                    "create",
                    label,
                    "--description",
                    "Contributor task label",
                    "--color",
                    "1d76db",
                ],
                capture_output=True,
                check=False,
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", default=False, help="Preview without creating issues"
    )
    parser.add_argument(
        "--publish", action="store_true", default=False, help="Create issues via gh CLI"
    )
    parser.add_argument("--issue", help="Publish a single issue by number prefix (e.g. 01)")
    args = parser.parse_args()

    if not args.dry_run and not args.publish:
        parser.print_help()
        print("\nPlease specify either --dry-run to preview or --publish to create issues.")
        sys.exit(1)

    issue_files = sorted(TASKS_DIR.glob("[0-9]*.md"))
    if not issue_files:
        sys.exit(f"No task files found in {TASKS_DIR}")

    if args.issue:
        issue_files = [f for f in issue_files if f.name.startswith(args.issue)]
        if not issue_files:
            sys.exit(f"No task file matching prefix '{args.issue}'")

    issues = [parse_issue(f) for f in issue_files]
    all_labels = {lbl for iss in issues for lbl in iss["labels"]}

    print(f"Found {len(issues)} contributor issues in {TASKS_DIR}")
    existing_titles = set()
    if args.publish:
        ensure_labels(all_labels, dry_run=False)
        try:
            res = subprocess.run(
                ["gh", "issue", "list", "--state", "all", "--limit", "200", "--json", "title"],
                capture_output=True,
                text=True,
                check=True,
            )
            import json
            existing_titles = {item["title"].strip() for item in json.loads(res.stdout)}
        except Exception as e:
            print(f"[!] Warning: Could not fetch existing issues: {e}")

    for idx, iss in enumerate(issues, start=1):
        print(f"\n--- [{idx}/{len(issues)}] {iss['file']} ---")
        print(f"Title : {iss['title']}")
        print(f"Labels: {', '.join(iss['labels'])}")
        print(f"Body  : {len(iss['body'])} chars")

        if iss["title"].strip() in existing_titles:
            print("[⏩] Skipped: Issue with this title already exists on GitHub.")
            continue

        if args.publish:
            cmd = [
                "gh",
                "issue",
                "create",
                "--title",
                str(iss["title"]),
                "--body",
                str(iss["body"]),
            ]
            for label in iss["labels"]:
                cmd.extend(["--label", label])

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                print(f"[✓] Created: {result.stdout.strip()}")
            except subprocess.CalledProcessError as err:
                print(f"[✗] Failed to create issue: {err.stderr.strip()}", file=sys.stderr)
        else:
            print("[Dry-run] Not published. Use --publish to create.")


if __name__ == "__main__":
    main()
