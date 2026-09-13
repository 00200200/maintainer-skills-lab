#!/usr/bin/env python3
"""Render the README workflow illustration. Optional dependency: Pillow."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def font_path(bold=False):
    suffix = " Bold" if bold else ""
    candidates = [
        Path(f"/System/Library/Fonts/Supplemental/Arial{suffix}.ttf"),
        Path(f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf"),
    ]
    return next((str(path) for path in candidates if path.is_file()), None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", default=font_path())
    parser.add_argument("--bold-font", default=font_path(True))
    args = parser.parse_args()
    if not args.font or not args.bold_font:
        parser.error("Pass --font and --bold-font paths to TrueType fonts")
    fonts = {
        "title": ImageFont.truetype(args.bold_font, 26),
        "body": ImageFont.truetype(args.font, 18),
        "small": ImageFont.truetype(args.font, 15),
        "label": ImageFont.truetype(args.bold_font, 17),
    }
    frames = []
    for frame in range(48):
        image = Image.new("RGB", (1200, 310), "#101923")
        draw = ImageDraw.Draw(image)
        draw.text(
            (36, 24),
            "Edit one workflow. Keep every version in sync.",
            font=fonts["title"],
            fill="#edf4f7",
        )
        draw.rounded_rectangle((36, 92, 276, 190), radius=12, fill="#23332d", outline="#bced85")
        draw.text((57, 112), "skills / mkl-humanize", font=fonts["small"], fill="#bced85")
        draw.text((57, 141), "SKILL.md", font=fonts["title"], fill="#edf4f7")
        draw.line((278, 142, 437, 142), fill="#596e7a", width=2)
        draw.text((312, 107), "kit.py sync", font=fonts["small"], fill="#a9b9c8")
        draw.line((437, 79, 437, 207), fill="#596e7a", width=2)
        targets = [
            ("Codex", "Native files", "#bced85"),
            ("Claude Code", "Native files", "#e9b293"),
            ("Cursor", "Native files", "#b9b7f5"),
            ("Grok Bot", "Markdown recipe", "#83d2e9"),
        ]
        for index in range(4):
            x = 476 + index % 2 * 345
            y = 65 + index // 2 * 105
            draw.line((437, y + 35, x, y + 35), fill="#596e7a", width=2)
        for index, (label, detail, accent) in enumerate(targets):
            x = 476 + index % 2 * 345
            y = 65 + index // 2 * 105
            draw.rounded_rectangle(
                (x, y, x + 306, y + 76), radius=10, fill="#192733", outline="#3b505e"
            )
            draw.ellipse((x + 19, y + 17, x + 27, y + 25), fill=accent)
            draw.text((x + 39, y + 11), label, font=fonts["label"], fill="#eef4f8")
            draw.text((x + 19, y + 42), detail, font=fonts["small"], fill="#a9b9c8")
            pulse = (frame / 48 + index / 4) % 1
            radius = 3 + int(2 * math.sin(pulse * math.pi))
            px = 282 + int(pulse * 148)
            draw.ellipse((px - radius, 142 - radius, px + radius, 142 + radius), fill=accent)
        draw.text(
            (36, 270),
            "Workflow illustration · Grok Bot requires manual setup in the app.",
            font=fonts["small"],
            fill="#a9b9c8",
        )
        frames.append(image)
    frames[0].save(
        ROOT / "assets/workflow.gif",
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
        optimize=True,
    )
    print("Rendered assets/workflow.gif")


if __name__ == "__main__":
    main()
