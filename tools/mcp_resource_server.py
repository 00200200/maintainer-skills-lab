"""tools/mcp_resource_server.py - Zero-dependency MCP Resource & Prompt Server.

Exposes MaintainerSkillsLab skills and documentation as on-demand MCP Resources
(`resources/list`, `resources/read`) and Prompts (`prompts/list`, `prompts/get`).
Reduces initial system prompt context bloat from >15,000 tokens to under 200 tokens
in MCP-aware environments (Claude Desktop, Cursor, Zed, Windsurf, Continue).

Zero external dependencies (Python 3.11+ standard library only).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Match frontmatter YAML metadata in SKILL.md
FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass
class SkillResource:
    name: str
    description: str
    uri: str
    body: str
    file_path: Path


# =============================================================================
# Library Indexer
# =============================================================================


def parse_skill_file(skill_path: Path) -> SkillResource | None:
    """Parses frontmatter and body from a SKILL.md file."""
    try:
        content = skill_path.read_text(encoding="utf-8")
    except OSError:
        return None

    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        return None

    front_text, body = match.group(1), match.group(2)
    name: str | None = None
    description: str = ""

    for line in front_text.splitlines():
        line = line.strip()
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip().strip("\"'")
        elif line.startswith("description:"):
            description = line.split(":", 1)[1].strip().strip("\"'")

    if not name:
        name = skill_path.parent.name

    return SkillResource(
        name=name,
        description=description,
        uri=f"mkl://skills/{name}",
        body=body.strip(),
        file_path=skill_path,
    )


def index_skills(repo_root: Path) -> dict[str, SkillResource]:
    """Indexes all skills under skills/*/SKILL.md."""
    skills_dir = repo_root / "skills"
    indexed: dict[str, SkillResource] = {}
    if not skills_dir.exists():
        return indexed

    for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
        resource = parse_skill_file(skill_file)
        if resource:
            indexed[resource.name] = resource

    return indexed


def resolve_doc_resource(repo_root: Path, doc_rel_path: str) -> tuple[str, str] | None:
    """Resolves a document resource safely under docs/, guarding against path traversal."""
    # Prevent traversal attacks
    clean_rel = Path(doc_rel_path)
    if ".." in clean_rel.parts or clean_rel.is_absolute():
        return None

    target = (repo_root / "docs" / clean_rel).resolve()
    docs_root = (repo_root / "docs").resolve()

    if not str(target).startswith(str(docs_root)):
        return None

    if not target.exists() or not target.is_file():
        # Try appending .md
        if not target.suffix:
            target = target.with_suffix(".md")
            if not target.exists() or not target.is_file():
                return None
        else:
            return None

    try:
        content = target.read_text(encoding="utf-8")
        title = target.stem.replace("-", " ").title()
        return title, content
    except OSError:
        return None


# =============================================================================
# MCP JSON-RPC 2.0 Request Handlers
# =============================================================================


class McpResourceServer:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.skills = index_skills(self.repo_root)

    def handle_initialize(self, _params: dict) -> dict:
        return {
            "protocolVersion": "2024-11-05",
            "serverInfo": {
                "name": "maintainer-skills-lab",
                "version": "0.2.0",
            },
            "capabilities": {
                "resources": {"listChanged": False},
                "prompts": {"listChanged": False},
            },
        }

    def handle_resources_list(self, _params: dict) -> dict:
        resources = []
        for skill in self.skills.values():
            resources.append(
                {
                    "uri": skill.uri,
                    "name": skill.name,
                    "description": skill.description or f"Maintainer skill: {skill.name}",
                    "mimeType": "text/markdown",
                }
            )

        # Index markdown guides under docs/ if present
        docs_dir = self.repo_root / "docs"
        if docs_dir.exists():
            for doc_file in sorted(docs_dir.rglob("*.md")):
                if doc_file.is_file() and not any(part.startswith(".") for part in doc_file.parts):
                    try:
                        rel = doc_file.relative_to(docs_dir)
                        resources.append(
                            {
                                "uri": f"mkl://docs/{rel}",
                                "name": f"doc:{rel.stem}",
                                "description": f"Documentation: {rel.stem.replace('-', ' ').title()}",
                                "mimeType": "text/markdown",
                            }
                        )
                    except ValueError:
                        pass

        return {"resources": resources}

    def handle_resources_read(self, params: dict) -> dict:
        uri = params.get("uri", "")
        if not uri.startswith("mkl://"):
            raise ValueError(f"Unsupported URI scheme: {uri}")

        path_part = uri.removeprefix("mkl://")

        if path_part.startswith("skills/"):
            skill_name = path_part.removeprefix("skills/")
            if skill_name in self.skills:
                skill = self.skills[skill_name]
                return {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "text/markdown",
                            "text": skill.body,
                        }
                    ]
                }
            raise FileNotFoundError(f"Skill resource not found: {skill_name}")

        if path_part.startswith("docs/"):
            doc_rel = path_part.removeprefix("docs/")
            resolved = resolve_doc_resource(self.repo_root, doc_rel)
            if resolved:
                _, content = resolved
                return {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "text/markdown",
                            "text": content,
                        }
                    ]
                }
            raise FileNotFoundError(f"Document resource not found: {doc_rel}")

        raise ValueError(f"Unknown resource namespace in URI: {uri}")

    def handle_prompts_list(self, _params: dict) -> dict:
        prompts = []
        for skill in self.skills.values():
            prompts.append(
                {
                    "name": skill.name,
                    "description": skill.description or f"Run maintainer skill {skill.name}",
                    "arguments": [
                        {
                            "name": "context",
                            "description": "Optional context or specific target files for the skill",
                            "required": False,
                        }
                    ],
                }
            )
        return {"prompts": prompts}

    def handle_prompts_get(self, params: dict) -> dict:
        prompt_name = params.get("name", "")
        if prompt_name not in self.skills:
            raise FileNotFoundError(f"Prompt not found: {prompt_name}")

        skill = self.skills[prompt_name]
        user_ctx = params.get("arguments", {}).get("context", "")

        prompt_text = skill.body
        if user_ctx:
            prompt_text = f"{prompt_text}\n\n## User Context\n{user_ctx}"

        return {
            "description": skill.description,
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": prompt_text,
                    },
                }
            ],
        }

    def dispatch(self, request: dict) -> dict | None:
        """Dispatches an incoming JSON-RPC 2.0 request or notification."""
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        # Handle notifications (no response expected)
        if req_id is None:
            return None

        try:
            if method == "initialize":
                result = self.handle_initialize(params)
            elif method == "ping":
                result = {}
            elif method == "resources/list":
                result = self.handle_resources_list(params)
            elif method == "resources/read":
                result = self.handle_resources_read(params)
            elif method == "prompts/list":
                result = self.handle_prompts_list(params)
            elif method == "prompts/get":
                result = self.handle_prompts_get(params)
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}",
                    },
                }

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result,
            }
        except FileNotFoundError as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32602,
                    "message": str(e),
                },
            }
        except ValueError as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32602,
                    "message": str(e),
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32603,
                    "message": f"Internal server error: {e}",
                },
            }

    def run_stdio(self) -> None:
        """Runs the JSON-RPC stdio event loop."""
        for line in sys.stdin:
            line_str = line.strip()
            if not line_str:
                continue

            try:
                request = json.loads(line_str)
            except json.JSONDecodeError as e:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": f"Parse error: {e}",
                    },
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()
                continue

            response = self.dispatch(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()


# =============================================================================
# Client Configuration Generators
# =============================================================================


def generate_client_config(target: str, repo_root: Path) -> str:
    """Generates JSON client configuration snippets for popular MCP clients."""
    server_path = (repo_root / "tools" / "mcp_resource_server.py").resolve()
    python_bin = sys.executable

    if target == "claude":
        config = {
            "mcpServers": {
                "maintainer-skills-lab": {
                    "command": python_bin,
                    "args": [str(server_path), "--root", str(repo_root)],
                }
            }
        }
    elif target == "cursor":
        config = {
            "mcpServers": {
                "maintainer-skills-lab": {
                    "command": python_bin,
                    "args": [str(server_path), "--root", str(repo_root)],
                }
            }
        }
    elif target == "zed":
        config = {
            "context_servers": {
                "maintainer-skills-lab": {
                    "command": {
                        "path": python_bin,
                        "args": [str(server_path), "--root", str(repo_root)],
                    }
                }
            }
        }
    else:
        raise ValueError(f"Unknown config target: {target}")

    return json.dumps(config, indent=2)


# =============================================================================
# CLI Main
# =============================================================================


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Maintainer Skills Lab MCP Resource & Prompt Server."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Maintainer Skills Lab repository root directory",
    )
    parser.add_argument(
        "--generate-config",
        choices=["claude", "cursor", "zed"],
        help="Print client JSON configuration snippet and exit",
    )

    args = parser.parse_args(argv)

    if args.generate_config:
        print(generate_client_config(args.generate_config, args.root))
        return 0

    server = McpResourceServer(args.root)
    server.run_stdio()
    return 0


if __name__ == "__main__":
    sys.exit(main())
