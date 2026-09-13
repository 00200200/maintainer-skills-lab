#!/usr/bin/env python3
"""List evidence that changed between a draft and its same-language rewrite.

Compares code, URLs, placeholders, numbers and quotations exactly, and counts
negation and hedge words in English and Polish. It cannot judge meaning: a clean
result only says these tokens survived. Standard library only; Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

FENCED = re.compile(r"```.*?```|~~~.*?~~~", re.S)
INLINE = re.compile(r"`[^`\n]+`")
URL = re.compile(r"https?://[^\s<>()\[\]\"']+")
PLACEHOLDER = re.compile(
    r"\{\{[^{}\n]+\}\}|\{[\w.:-]+\}|%\(\w+\)[sdifr]|%[sdif]|\$\{\w+\}|\$[A-Z_][A-Z0-9_]*"
)
QUOTE = re.compile(r'"([^"\n]+)"|“([^”\n]+)”|„([^”“\n]+)[”“]|«([^»\n]+)»')
NUMBER = re.compile(r"(?<![\w.])[-+]?\d+(?:[.,]\d+)*%?")
WORDS = {
    "negation": (
        "not no never none nobody nothing neither nor without cannot can't don't doesn't "
        "didn't isn't aren't wasn't weren't won't hasn't haven't hadn't shouldn't wouldn't "
        "nie nigdy bez żaden żadna żadne żadnych ani nikt nic"
    ),
    "hedge": (
        "may might could likely unlikely possibly probably perhaps approximately roughly "
        "estimated preliminary only yet "
        "może mogą prawdopodobnie chyba około szacunkowo wstępnie tylko jeszcze"
    ),
}


def evidence(text: str) -> dict[str, Counter]:
    found = {}
    for kind, pattern in (("code", FENCED), ("code", INLINE), ("url", URL)):
        matches = pattern.findall(text)
        found.setdefault(kind, Counter()).update(m.rstrip(".,;:!?") for m in matches)
        text = pattern.sub(" ", text)
    found["placeholder"] = Counter(PLACEHOLDER.findall(text))
    text = PLACEHOLDER.sub(" ", text)
    found["quotation"] = Counter(next(part for part in m if part) for m in QUOTE.findall(text))
    found["number"] = Counter(NUMBER.findall(text))
    lowered = text.lower().replace("’", "'")
    for kind, words in WORDS.items():
        counts = Counter()
        for word in words.split():
            hits = len(re.findall(rf"(?<![\w']){re.escape(word)}(?![\w'])", lowered))
            if hits:
                counts[word] = hits
        found[kind] = counts
    return found


def compare(source: str, rewrite: str) -> list[dict]:
    before, after = evidence(source), evidence(rewrite)
    differences = []
    for kind in ("code", "url", "placeholder", "quotation", "number", "negation", "hedge"):
        for value in sorted(set(before[kind]) | set(after[kind])):
            old, new = before[kind][value], after[kind][value]
            if old != new:
                change = "dropped" if new < old else "added"
                differences.append(
                    {"kind": kind, "value": value, "change": change, "source": old, "rewrite": new}
                )
    return differences


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="original draft")
    parser.add_argument("rewrite", type=Path, help="edited version in the same language")
    parser.add_argument("--json", action="store_true", help="print a JSON report")
    args = parser.parse_args(argv)
    try:
        source = args.source.read_text(encoding="utf-8")
        rewrite = args.rewrite.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print(f"check_facts: {exc}", file=sys.stderr)
        return 2
    differences = compare(source, rewrite)
    if args.json:
        status = "review" if differences else "preserved"
        print(json.dumps({"status": status, "differences": differences}, ensure_ascii=False))
    elif differences:
        print(f"Review {len(differences)} change(s); restore each one or explain why it is safe:")
        for item in differences:
            print(
                f"- {item['kind']} {item['change']}: {item['value']!r} "
                f"({item['source']} -> {item['rewrite']})"
            )
    else:
        print("Code, URLs, placeholders, quotations, numbers, negations and hedges match.")
        print("This does not check meaning, emphasis or attribution.")
    return 1 if differences else 0


if __name__ == "__main__":
    raise SystemExit(main())
