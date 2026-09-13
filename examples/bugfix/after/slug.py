import re


def slugify(title: str) -> str:
    letters_and_spaces = re.sub(r"[^a-z0-9\s]", "", title.lower())
    return "-".join(letters_and_spaces.split())
