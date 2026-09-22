#!/usr/bin/env python3
"""Check Skills CLI resource copying and removal in disposable projects."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION = "1.5.26"
TARGETS = {
    "codex": ".agents",
    "claude-code": ".claude",
    "cursor": ".agents",
    "opencode": ".agents",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(command, directory, env, expected=0):
    result = subprocess.run(
        command, cwd=directory, env=env, capture_output=True, text=True, timeout=50, check=False
    )
    require(
        result.returncode == expected,
        f"{Path(command[0]).name} exited {result.returncode}, expected {expected}: "
        f"{result.stderr[-2000:]}",
    )
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", default=shutil.which("node"), help="Node.js 22.20+ executable")
    parser.add_argument("--skills", default=shutil.which("skills"), help="Skills CLI JS entrypoint")
    args = parser.parse_args()
    if not args.node or not args.skills:
        parser.error("provide --node and --skills, or put both executables on PATH")
    node, skills = str(Path(args.node).resolve()), str(Path(args.skills).resolve())
    env = dict(os.environ, DISABLE_TELEMETRY="1", NODE_DISABLE_COMPILE_CACHE="1")
    cli = [node, skills]
    results = []
    with tempfile.TemporaryDirectory(prefix="mkl-skills-cli-") as temporary:
        root = Path(temporary)
        version = run([node, "--version"], root, env).strip()
        parts = tuple(int(p) for p in version.removeprefix("v").split("."))
        require(parts >= (22, 20, 0), "Node.js 22.20.0+ is required")
        require(run([*cli, "--version"], root, env).strip() == VERSION, f"Use Skills CLI {VERSION}")
        source = ROOT / "skills/mkl-humanize"
        # Match the library's resource rules; local Python caches are not skills.
        expected = {
            p.relative_to(source): p.read_bytes()
            for p in source.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
        }
        for target, folder in TARGETS.items():
            project = root / target
            project.mkdir()
            sentinel = project / "keep.txt"
            sentinel.write_text("Unrelated project file.\n")
            run(
                [
                    *cli,
                    "add",
                    str(ROOT),
                    "--skill",
                    "mkl-humanize",
                    "--agent",
                    target,
                    "--copy",
                    "--yes",
                    "--json",
                ],
                project,
                env,
            )
            installed = project / folder / "skills/mkl-humanize"
            actual = {
                p.relative_to(installed): p.read_bytes()
                for p in installed.rglob("*")
                if p.is_file()
            }
            require(actual == expected, f"{target}: copied resources differ from canonical source")
            require(
                not any(p.is_symlink() for p in installed.rglob("*")),
                f"{target}: expected regular copies",
            )
            require((project / "skills-lock.json").is_file(), f"{target}: missing lock file")
            listing = run([*cli, "list", "--agent", target, "--json"], project, env)
            require("mkl-humanize" in listing, f"{target}: installed skill not listed")
            draft, edit = project / "draft.md", project / "edit.md"
            draft.write_text("Budget: 1e3. Windows is not tested.")
            script = installed / "scripts/check_facts.py"
            for content, code in ((draft.read_text(), 0), ("Budget: 1e6. Windows is tested.", 1)):
                edit.write_text(content)
                report = json.loads(
                    run(
                        [sys.executable, str(script), str(draft), str(edit), "--json"],
                        project,
                        env,
                        code,
                    )
                )
                require(
                    bool(report["differences"]) == bool(code), f"{target}: incorrect checker report"
                )
            run([*cli, "remove", "mkl-humanize", "--yes"], project, env)
            require(not installed.exists(), f"{target}: skill resources remain after removal")
            require(
                sentinel.read_text() == "Unrelated project file.\n",
                f"{target}: unrelated file changed",
            )
            require(draft.exists() and edit.exists(), f"{target}: draft files removed")
            results.append(target)
    print(
        json.dumps(
            {
                "skills_cli": VERSION,
                "node": version,
                "targets": results,
                "source": "local checkout",
                "resources_match": True,
                "installed_checker_executed": True,
                "removal_verified": True,
                "model_session_started": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
