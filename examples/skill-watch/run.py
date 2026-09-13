#!/usr/bin/env python3
"""Exercise Skill Watch against an authored documentation change, without network."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from skill_watch import Watch  # noqa: E402

HERE = Path(__file__).resolve().parent


def prepare(project):
    owner = project / "skills/mkl-training-demo/SKILL.md"
    owner.parent.mkdir(parents=True)
    owner.write_text(
        "Check https://docs.example.org/training before changing smoke_run.\n"
        "During smoke_run, verify that a checkpoint file is created.\n"
    )
    (project / "agents").mkdir()
    (project / "agents/mkl-demo-investigator.toml").write_text('skills = ["mkl-training-demo"]\n')
    (project / "skill-watch.toml").write_text(
        'version = 1\n\n[[sources]]\nid = "training"\nfile = "training.html"\n'
        'format = "html"\nstart = "One-batch smoke test"\nend = "Full training"\n'
        'owners = ["skills/mkl-training-demo/SKILL.md"]\n'
    )
    shutil.copyfile(HERE / "before.html", project / "training.html")


def exercise(project):
    prepare(project)
    watch = Watch(project)
    watch.snapshot()
    original = watch.state.read_bytes()
    unchanged = watch.check()
    shutil.copyfile(HERE / "after.html", project / "training.html")
    changed = watch.check()
    repeated = watch.check()
    preserved = original == watch.state.read_bytes()
    current = changed["sources"][0]["current"]["sha256"]
    watch.accept("training", current)
    accepted = watch.check()
    verified = (
        unchanged["status"] == "unchanged"
        and changed["status"] == repeated["status"] == "review-needed"
        and preserved
        and accepted["status"] == "unchanged"
        and changed["sources"][0]["agents"] == ["agents/mkl-demo-investigator.toml"]
    )
    return {
        "evaluation_kind": "authored offline fixture; no live-agent evaluation",
        "verified": verified,
        "initial": unchanged["status"],
        "changed": changed["status"],
        "repeated": repeated["status"],
        "baseline_preserved_until_accept": preserved,
        "after_explicit_accept": accepted["status"],
        "affected": changed["sources"][0]["owners"] + changed["sources"][0]["agents"],
        "diff": changed["sources"][0]["diff"],
    }


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="mkl-watch-demo-") as directory:
        report = exercise(Path(directory))
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["verified"] else 1)
