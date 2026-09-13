#!/usr/bin/env python3
"""Refresh aggregate README statistics using the maintainer's existing gh login."""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from datetime import UTC, datetime
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "00200200/maintainer-skills-lab"


def github(endpoint: str, *, paginate: bool = False):
    command = ["gh", "api", "-H", "Accept: application/vnd.github.star+json", endpoint]
    if paginate:
        command += ["--paginate", "--slurp"]
    result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=60)
    return json.loads(result.stdout)


def aggregate(repo: dict, pages: list, traffic: dict, observed: str) -> dict:
    # Use all pages, but never persist account names, IDs, or profile URLs.
    dates = Counter(entry["starred_at"][:10] for page in pages for entry in page)
    if sum(dates.values()) != repo["stargazers_count"]:
        raise ValueError("Star count changed during collection; retry to get a consistent snapshot")
    for key in ("count", "uniques", "views"):
        if key not in traffic:
            raise ValueError("Traffic unavailable; refusing to report missing data as zero")
    if not traffic["views"]:
        raise ValueError("Traffic window unavailable; keeping the previous snapshot")
    days = sorted(traffic["views"], key=lambda day: day["timestamp"])
    return {
        "repository": REPO,
        "observed_on_utc": observed,
        "created_on_utc": repo["created_at"][:10],
        "stars": repo["stargazers_count"],
        "forks": repo["forks_count"],
        "current_stargazers_by_date": dict(sorted(dates.items())),
        "views": {
            "window_start_utc": days[0]["timestamp"][:10],
            "window_end_utc": days[-1]["timestamp"][:10],
            "count": traffic["count"],
            "uniques": traffic["uniques"],
            "daily": [
                {"date": day["timestamp"][:10], "count": day["count"], "uniques": day["uniques"]}
                for day in days
            ],
        },
    }


def render(data: dict) -> str:
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="410" '
        'viewBox="0 0 1200 410" role="img" aria-labelledby="title desc">',
        '<title id="title">Maintainer Skills Lab community statistics</title>',
        '<desc id="desc">GitHub snapshot: '
        f"{data['stars']} stars, {data['forks']} forks, {data['views']['count']} views "
        f"and {data['views']['uniques']} unique visitors in the returned 14-day window. "
        "Star chart groups current stargazers by date starred; removed stars are excluded.</desc>",
        '<rect width="1200" height="410" rx="24" fill="#101923"/>',
        '<g font-family="Arial,Helvetica,sans-serif">',
    ]

    def text(x, y, value, size=16, color="#a9b9c8", extra=""):
        parts.append(
            f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" {extra}>'
            f"{escape(str(value))}</text>"
        )

    text(40, 40, "COMMUNITY / LIVE BADGES ABOVE · SNAPSHOT BELOW", 13, "#bced85")
    text(1160, 40, data["observed_on_utc"] + " UTC", 14, extra='text-anchor="end"')
    metrics = (
        ("STARS", data["stars"]),
        ("FORKS", data["forks"]),
        ("VIEWS · 14 DAYS", data["views"]["count"]),
        ("UNIQUE VISITORS · 14 DAYS", data["views"]["uniques"]),
    )
    for index, (label, value) in enumerate(metrics):
        x = 40 + index * 286
        text(x, 80, label, 12)
        text(x, 130, value, 44, "#eef4f8", 'font-weight="700"')
    parts.append('<path d="M40 159H1160" stroke="#2a3949"/>')
    text(40, 191, "STAR HISTORY", 13, "#bced85")
    text(1160, 191, "Current stargazers, grouped by date starred", 13, extra='text-anchor="end"')
    start = datetime.fromisoformat(data["created_on_utc"])
    end = datetime.fromisoformat(data["observed_on_utc"])
    span = max(1, (end - start).days)
    maximum = max(1, data["stars"])
    for fraction in (0, 0.5, 1):
        y = 307 - fraction * 88
        parts.append(f'<path d="M70 {y}H1160" stroke="#223140"/>')
    text(40, 224, maximum, 12)
    text(40, 312, 0, 12)
    points = []
    total = 0
    for day, count in data["current_stargazers_by_date"].items():
        total += count
        x = 70 + (datetime.fromisoformat(day) - start).days / span * 1090
        y = 307 - total / maximum * 88
        points.append((x, y, total))
    if len(points) > 1:
        # A step changes only when a current stargazer actually starred the repository.
        x, y, _ = points[0]
        path = f"M{x:.1f} {y:.1f}"
        for x, y, _ in points[1:]:
            path += f"H{x:.1f}V{y:.1f}"
        parts.append(f'<path d="{path}" fill="none" stroke="#bced85" stroke-width="3"/>')
    for x, y, _ in points:
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#bced85"/>')
    if len(points) <= 1:
        text(1160, 270, "The beginning. Each dot comes from GitHub.", 16, extra='text-anchor="end"')
    text(70, 335, data["created_on_utc"], 12)
    if start != end:
        text(1160, 335, data["observed_on_utc"], 12, extra='text-anchor="end"')
    views = data["views"]
    text(40, 380, f"Views: {views['window_start_utc']} to {views['window_end_utc']} UTC.", 13)
    text(
        1160, 380, "Source: GitHub API · Removed stars are excluded", 13, extra='text-anchor="end"'
    )
    return "\n".join([*parts, "</g></svg>\n"])


def main() -> int:
    try:
        repo = github(f"repos/{REPO}")
        pages = github(f"repos/{REPO}/stargazers?per_page=100", paginate=True)
        traffic = github(f"repos/{REPO}/traffic/views")
        data = aggregate(repo, pages, traffic, datetime.now(UTC).date().isoformat())
        outputs = {
            ROOT / "assets/community.json": json.dumps(data, indent=2) + "\n",
            ROOT / "assets/community.svg": render(data),
        }
        for path, content in outputs.items():
            if not path.exists() or path.read_text() != content:
                path.write_text(content, encoding="utf-8")
        print("Updated aggregate GitHub snapshot; no visitor or stargazer identities saved.")
        return 0
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError) as exc:
        # Do not print a response body, environment, or credentials from a failed request.
        print(f"Statistics refresh failed ({type(exc).__name__}); no new snapshot confirmed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
