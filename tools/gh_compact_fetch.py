#!/usr/bin/env python3
"""tools/gh_compact_fetch.py - Token-Optimized GraphQL GitHub Issue & PR Fetcher.

Fetches GitHub issue and pull request discussion threads via GraphQL API,
filtering bot noise, email reply chains, and redundant signatures to reduce
context token ingestion by 75% to 85%.

Standard library only (Python 3.11+). Works via `gh api graphql` CLI or
direct HTTPS requests with GITHUB_TOKEN / GH_TOKEN.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

KNOWN_BOT_NAMES = {
    "codecov",
    "codecov[bot]",
    "dependabot",
    "dependabot[bot]",
    "github-actions",
    "github-actions[bot]",
    "stale",
    "stale[bot]",
    "vercel",
    "vercel[bot]",
    "netlify",
    "netlify[bot]",
    "sonarcloud",
    "sonarcloud[bot]",
    "lgtm-com",
    "cla-assistant",
    "snyk-bot",
    "coveralls",
    "renovate",
    "renovate[bot]",
    "imgbot",
    "imgbot[bot]",
    "app/dependabot",
}

EMAIL_REPLY_HEADER_RE = re.compile(
    r"^(?:On\s+.*,\s+.*wrote:|From:\s+.*|Sent:\s+.*|---+\s*Original Message\s*---+)",
    re.IGNORECASE | re.MULTILINE,
)

SIGNATURE_PATTERNS = [
    re.compile(r"^--\s*$", re.MULTILINE),
    re.compile(r"^Sent from my (?:iPhone|iPad|Android|Galaxy|mobile device).*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^Get Outlook for (?:iOS|Android).*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^(?:Best regards|Regards|Cheers|Thanks|Warmly|Sincerely),\s*\n[^\n]+$", re.IGNORECASE | re.MULTILINE),
]


def is_bot_user(login: Optional[str]) -> bool:
    if not login:
        return False
    login_clean = login.strip().lower()
    if login_clean in KNOWN_BOT_NAMES:
        return True
    if login_clean.endswith("[bot]") or login_clean.endswith("-bot"):
        return True
    if login_clean.startswith("app/"):
        return True
    return False


def strip_quoted_replies(text: str) -> str:
    """Strips email-style quote headers and consecutive blockquote lines ('> ...')."""
    lines = text.splitlines()
    cleaned_lines: List[str] = []
    in_code_block = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            cleaned_lines.append(line)
            continue

        if not in_code_block:
            # Check for email reply introduction header
            if EMAIL_REPLY_HEADER_RE.match(line):
                # Stop including lines from quoted chain onwards
                break
            if stripped.startswith(">"):
                # Omit email quoted line
                continue

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def strip_signatures(text: str) -> str:
    """Strips email signatures, mobile footers, and standard separators."""
    res = text
    # Strip signature delimiter '-- \n...'
    parts = re.split(r"\n--\s*\n", res, maxsplit=1)
    if len(parts) > 1:
        res = parts[0]

    for pat in SIGNATURE_PATTERNS:
        res = pat.sub("", res)

    return res


def clean_body_text(text: Optional[str], strip_quotes: bool = True, strip_sigs: bool = True) -> str:
    if not text:
        return ""
    cleaned = text
    if strip_quotes:
        cleaned = strip_quoted_replies(cleaned)
    if strip_sigs:
        cleaned = strip_signatures(cleaned)

    # Normalize excessive blank lines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def estimate_tokens(text: str) -> int:
    """Conservative token estimation (~4 characters per token)."""
    return max(1, (len(text) + 3) // 4)


def parse_target(target: str, kind: Optional[str] = None) -> Tuple[str, str, int, str]:
    """Parses owner/repo#number, URL, or separate tokens into (owner, repo, number, kind)."""
    target = target.strip()

    # URL format: https://github.com/owner/repo/(issues|pull)/123
    url_match = re.match(r"^https?://github\.com/([^/]+)/([^/]+)/(issues|pull)/(\d+)", target)
    if url_match:
        owner, repo, url_kind, num_str = url_match.groups()
        resolved_kind = "pr" if url_kind == "pull" else "issue"
        return owner, repo, int(num_str), kind or resolved_kind

    # owner/repo#number
    hash_match = re.match(r"^([^/]+)/([^#]+)#(\d+)$", target)
    if hash_match:
        owner, repo, num_str = hash_match.groups()
        return owner, repo, int(num_str), kind or "issue"

    # owner/repo 123
    space_match = re.match(r"^([^/\s]+)/([^\s]+)\s+(\d+)$", target)
    if space_match:
        owner, repo, num_str = space_match.groups()
        return owner, repo, int(num_str), kind or "issue"

    raise ValueError(
        f"Invalid target format '{target}'. Expected 'owner/repo#123' or 'https://github.com/owner/repo/issues/123'"
    )


ISSUE_GRAPHQL_QUERY = """
query($owner: String!, $repo: String!, $number: Int!, $maxComments: Int!) {
  repository(owner: $owner, name: $repo) {
    issue(number: $number) {
      title
      state
      createdAt
      body
      author { login }
      authorAssociation
      labels(first: 20) { nodes { name } }
      comments(first: $maxComments) {
        nodes {
          createdAt
          body
          author { login }
          authorAssociation
        }
      }
    }
  }
}
"""

PR_GRAPHQL_QUERY = """
query($owner: String!, $repo: String!, $number: Int!, $maxComments: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      title
      state
      createdAt
      body
      baseRefName
      headRefName
      author { login }
      authorAssociation
      labels(first: 20) { nodes { name } }
      comments(first: $maxComments) {
        nodes {
          createdAt
          body
          author { login }
          authorAssociation
        }
      }
    }
  }
}
"""


def execute_graphql(query: str, variables: Dict[str, Any], token: Optional[str] = None) -> Dict[str, Any]:
    """Executes GraphQL query via `gh api graphql` or urllib."""
    # 1. Try `gh` CLI if available
    gh_bin = shutil.which("gh")
    if gh_bin:
        cmd = [gh_bin, "api", "graphql", "-f", f"query={query}"]
        for k, v in variables.items():
            if isinstance(v, int):
                cmd.extend(["-F", f"{k}={v}"])
            else:
                cmd.extend(["-f", f"{k}={str(v)}"])
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            return json.loads(proc.stdout)

    # 2. Fall back to urllib.request
    auth_token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not auth_token:
        raise RuntimeError(
            "Neither `gh` CLI nor GITHUB_TOKEN/GH_TOKEN environment variable found. "
            "Please install `gh` or provide a GitHub token."
        )

    headers = {
        "Authorization": f"bearer {auth_token}",
        "Content-Type": "application/json",
        "User-Agent": "MaintainerSkillsLab-gh_compact_fetch",
    }
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request("https://api.github.com/graphql", data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        raise RuntimeError(f"GitHub GraphQL API returned HTTP {e.code}: {body}") from e


def process_thread_data(
    raw_response: Dict[str, Any],
    kind: str,
    owner: str,
    repo: str,
    number: int,
    exclude_bots: bool = True,
    strip_quotes: bool = True,
    strip_sigs: bool = True,
) -> Dict[str, Any]:
    """Processes and compresses raw GraphQL response into compact structured payload."""
    repo_data = raw_response.get("data", {}).get("repository", {})
    item_data = repo_data.get("pullRequest" if kind == "pr" else "issue")

    if not item_data:
        errors = raw_response.get("errors", [])
        err_msg = "; ".join(e.get("message", "Unknown error") for e in errors) or "Item not found"
        raise ValueError(f"Could not fetch {kind} {owner}/{repo}#{number}: {err_msg}")

    title = item_data.get("title", "")
    state = item_data.get("state", "UNKNOWN")
    created_at = item_data.get("createdAt", "")
    author_obj = item_data.get("author") or {}
    author_login = author_obj.get("login", "ghost")
    author_assoc = item_data.get("authorAssociation", "NONE")
    raw_body = item_data.get("body") or ""
    body = clean_body_text(raw_body, strip_quotes=strip_quotes, strip_sigs=strip_sigs)

    labels = [lbl.get("name") for lbl in item_data.get("labels", {}).get("nodes", []) if lbl.get("name")]

    all_comments_nodes = item_data.get("comments", {}).get("nodes", [])
    filtered_comments: List[Dict[str, Any]] = []
    omitted_bots: List[str] = []

    for c in all_comments_nodes:
        c_author_obj = c.get("author") or {}
        c_author = c_author_obj.get("login", "ghost")
        c_assoc = c.get("authorAssociation", "NONE")
        c_raw_body = c.get("body") or ""

        if exclude_bots and is_bot_user(c_author):
            omitted_bots.append(f"@{c_author}")
            continue

        c_cleaned = clean_body_text(c_raw_body, strip_quotes=strip_quotes, strip_sigs=strip_sigs)
        if not c_cleaned.strip():
            continue

        filtered_comments.append({
            "author": c_author,
            "association": c_assoc,
            "createdAt": c.get("createdAt", ""),
            "body": c_cleaned,
        })

    # Token calculations for stats
    raw_serialized = json.dumps(raw_response)
    raw_tokens = estimate_tokens(raw_serialized)

    return {
        "kind": kind,
        "owner": owner,
        "repo": repo,
        "number": number,
        "title": title,
        "state": state,
        "createdAt": created_at,
        "author": author_login,
        "authorAssociation": author_assoc,
        "labels": labels,
        "body": body,
        "comments": filtered_comments,
        "omitted_bots": omitted_bots,
        "total_comments_in_thread": len(all_comments_nodes),
        "raw_tokens_estimate": raw_tokens,
    }


def format_markdown(data: Dict[str, Any]) -> str:
    """Formats compacted data into high-density Markdown."""
    lines: List[str] = []
    kind_label = "PR" if data["kind"] == "pr" else "Issue"
    lines.append(f"# [{kind_label} #{data['number']}] {data['title']}")

    meta_parts = [
        f"**Author**: @{data['author']} ({data['authorAssociation']})",
        f"**State**: {data['state']}",
    ]
    if data["labels"]:
        meta_parts.append(f"**Labels**: {', '.join(data['labels'])}")
    lines.append(" | ".join(meta_parts))
    lines.append("")

    lines.append("### Description")
    if data["body"]:
        lines.append(data["body"])
    else:
        lines.append("*(No description provided)*")
    lines.append("")

    comments = data["comments"]
    omitted = data["omitted_bots"]
    bot_summary = ""
    if omitted:
        unique_bots = sorted(set(omitted))
        bot_summary = f", {len(omitted)} bot comments omitted: {', '.join(unique_bots)}"

    lines.append(f"### Discussion ({len(comments)} human comments{bot_summary})")
    if not comments:
        lines.append("*(No discussion comments)*")
    else:
        for idx, c in enumerate(comments, 1):
            date_short = c["createdAt"][:10] if c.get("createdAt") else ""
            date_suffix = f" on {date_short}" if date_short else ""
            lines.append(f"**@{c['author']}** ({c['association']}){date_suffix}:")
            lines.append(c["body"])
            if idx < len(comments):
                lines.append("")

    return "\n".join(lines)


def run_compact_fetch(
    target: str,
    kind: Optional[str] = None,
    exclude_bots: bool = True,
    strip_quotes: bool = True,
    strip_sigs: bool = True,
    max_comments: int = 100,
    as_json: bool = False,
    show_stats: bool = False,
    mock_data: Optional[Dict[str, Any]] = None,
    token: Optional[str] = None,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """High-level runner returning (output_string, stats_dict)."""
    owner, repo, number, resolved_kind = parse_target(target, kind=kind)

    if mock_data is not None:
        raw_resp = mock_data
    else:
        query = PR_GRAPHQL_QUERY if resolved_kind == "pr" else ISSUE_GRAPHQL_QUERY
        variables = {
            "owner": owner,
            "repo": repo,
            "number": number,
            "maxComments": max_comments,
        }
        raw_resp = execute_graphql(query, variables, token=token)

    data = process_thread_data(
        raw_resp,
        kind=resolved_kind,
        owner=owner,
        repo=repo,
        number=number,
        exclude_bots=exclude_bots,
        strip_quotes=strip_quotes,
        strip_sigs=strip_sigs,
    )

    if as_json:
        output_str = json.dumps(data, indent=2)
    else:
        output_str = format_markdown(data)

    compact_tokens = estimate_tokens(output_str)
    raw_tokens = data["raw_tokens_estimate"]
    savings_pct = max(0.0, 100.0 * (raw_tokens - compact_tokens) / max(1, raw_tokens))

    stats = {
        "raw_tokens": raw_tokens,
        "compact_tokens": compact_tokens,
        "savings_tokens": raw_tokens - compact_tokens,
        "savings_pct": round(savings_pct, 1),
    }

    if show_stats:
        stats_header = (
            f"\n<!-- Token Efficiency Stats: Raw REST/GraphQL: ~{raw_tokens} tokens | "
            f"Compact Output: ~{compact_tokens} tokens | "
            f"Reduction: {stats['savings_pct']}% (~{stats['savings_tokens']} tokens saved) -->\n"
        )
        output_str = output_str + stats_header

    return output_str, stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="GraphQL compact PR and issue fetcher for LLM context optimization."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--issue", metavar="TARGET", help="Fetch issue: owner/repo#123 or URL")
    group.add_argument("--pr", metavar="TARGET", help="Fetch PR: owner/repo#123 or URL")
    parser.add_argument("target", nargs="?", help="Positional target (e.g. owner/repo#123)")

    parser.add_argument("--include-bots", action="store_true", help="Include automated bot comments")
    parser.add_argument("--keep-quotes", action="store_true", help="Do not strip email quotes")
    parser.add_argument("--keep-signatures", action="store_true", help="Do not strip signatures")
    parser.add_argument("--max-comments", type=int, default=100, help="Maximum comments to fetch (default: 100)")
    parser.add_argument("--json", action="store_true", help="Output compact JSON instead of Markdown")
    parser.add_argument("--stats", action="store_true", help="Print token reduction statistics")
    parser.add_argument("--token", help="GitHub Personal Access Token (defaults to GITHUB_TOKEN)")
    parser.add_argument("--mock-file", help="Path to local JSON file for testing without network")

    args = parser.parse_args()

    target = args.issue or args.pr or args.target
    if not target:
        parser.error("Must specify a target via --issue, --pr, or positional argument.")

    kind = "pr" if args.pr else ("issue" if args.issue else None)

    mock_data = None
    if args.mock_file:
        with open(args.mock_file, "r", encoding="utf-8") as f:
            mock_data = json.load(f)

    try:
        output_str, _ = run_compact_fetch(
            target=target,
            kind=kind,
            exclude_bots=not args.include_bots,
            strip_quotes=not args.keep_quotes,
            strip_sigs=not args.keep_signatures,
            max_comments=args.max_comments,
            as_json=args.json,
            show_stats=args.stats,
            mock_data=mock_data,
            token=args.token,
        )
        print(output_str)
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
