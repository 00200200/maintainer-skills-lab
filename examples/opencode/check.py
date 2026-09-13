#!/usr/bin/env python3
"""Check exported-file discovery with OpenCode 1.18.30; no model session is started."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import kit  # noqa: E402

VERSION = "1.18.30"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def exercise(executable):
    skills, agents = kit.load_library()
    with tempfile.TemporaryDirectory(prefix="mkl-opencode-discovery-") as directory:
        root = Path(directory).resolve()
        project = root / "project"
        project.mkdir()
        (root / "home").mkdir()
        subprocess.run(["git", "init", "-q", str(project)], check=True, timeout=15)
        # Do not inherit credentials, client overrides, or the user's XDG state.
        env = {
            "PATH": os.environ.get("PATH", ""),
            "LANG": "en_US.UTF-8",
            "OPENCODE_TEST_HOME": str(root / "home"),
            "OPENCODE_DISABLE_AUTOUPDATE": "1",
            "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
            "OPENCODE_DISABLE_LSP_DOWNLOAD": "1",
            "OPENCODE_CONFIG_CONTENT": '{"autoupdate":false,"share":"disabled"}',
        }
        for kind in ("CONFIG", "DATA", "CACHE", "STATE"):
            env[f"XDG_{kind}_HOME"] = str(root / kind.lower())

        def run(*args):
            result = subprocess.run(
                [executable, *args],
                cwd=project,
                env=env,
                capture_output=True,
                text=True,
                timeout=45,
                check=True,
            )
            return result.stdout

        version = run("--version").strip()
        require(version == VERSION, f"Expected OpenCode {VERSION}, got {version}")

        def discovered(expected):
            entries = json.loads(run("debug", "skill"))
            actual = [entry for entry in entries if entry["name"].startswith("mkl-")]
            require(len(actual) == len(expected), "Unexpected number of library skills")
            require({entry["name"] for entry in actual} == set(expected), "Skill names differ")
            for entry in actual:
                source = skills[entry["name"]]
                require(entry["description"] == source["description"], "Description differs")
                require(entry["content"].strip() == source["body"].strip(), "Skill body differs")
                location = project / ".opencode/skills" / entry["name"] / "SKILL.md"
                require(Path(entry["location"]).resolve() == location, "Unexpected skill location")

        discovered([])
        kit.install("opencode", project, skill_names=["mkl-humanize"])
        discovered(["mkl-humanize"])
        kit.uninstall("opencode", project, skill_names=["mkl-humanize"])
        discovered([])
        kit.install("opencode", project)
        discovered(skills)
        for name, source in agents.items():
            agent = json.loads(run("debug", "agent", name))
            require(
                agent["name"] == name and agent["mode"] == "subagent", "Agent mode/name differs"
            )
            require(agent["description"] == source["description"], "Agent description differs")
            require(
                agent["prompt"].strip() == kit.agent_body(source, skills).strip(),
                "Agent prompt differs",
            )
        # Client diagnostics may create their own state, but must preserve our exports.
        for relative, data in kit.export_files("opencode").items():
            require((project / relative).read_bytes() == data, f"Client changed {relative}")
        kit.uninstall("opencode", project)
        discovered([])
        return {
            "opencode_version": version,
            "skills": len(skills),
            "agents": len(agents),
            "selected_install_discovery": True,
            "removal_discovery": True,
            "skill_content_and_agent_prompts_match": True,
            "model_session_started": False,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--opencode", default="opencode", help="OpenCode executable, version 1.18.30"
    )
    args = parser.parse_args()
    executable = shutil.which(args.opencode)
    if executable is None:
        parser.error("OpenCode executable not found; install the pinned CLI separately")
    try:
        print(json.dumps(exercise(str(Path(executable).resolve())), indent=2))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"OpenCode discovery check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
