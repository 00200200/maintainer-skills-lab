#!/usr/bin/env python3
"""Standardized Subagent Handoff Protocol for Modular Agent Delegation.

Protocol: mkl-subagent-handoff/v1
Zero external dependencies (pure Python standard library).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

PROTOCOL_VERSION = "mkl-subagent-handoff/v1"

ALLOWED_STATUSES = frozenset({"COMPLETED", "FAILED", "BLOCKED"})
ALLOWED_VERDICTS = frozenset(
    {"APPROVED", "REJECTED", "NEEDS_INFO", "CONFIRMED_BUG", "NOT_REPRODUCED", "PATCH_READY"}
)


@dataclass
class SubagentHandoffRequest:
    task_id: str
    delegator: str
    target_agent: str
    context: dict[str, Any]
    expected_output_schema: str = "verdict_artifact"
    protocol: str = PROTOCOL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


@dataclass
class SubagentHandoffResponse:
    task_id: str
    agent: str
    status: str
    summary: str
    verdict: str | None = None
    findings: list[dict[str, Any]] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    protocol: str = PROTOCOL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


def validate_handoff_request(data: dict[str, Any]) -> list[str]:
    """Validate a subagent handoff request payload against mkl-subagent-handoff/v1."""
    issues = []
    if not isinstance(data, dict):
        return ["Payload must be a JSON object"]

    protocol = data.get("protocol")
    if protocol != PROTOCOL_VERSION:
        issues.append(
            f"Invalid or missing protocol: expected '{PROTOCOL_VERSION}', got '{protocol}'"
        )

    for key in ("task_id", "delegator", "target_agent"):
        val = data.get(key)
        if not isinstance(val, str) or not val.strip():
            issues.append(f"Field '{key}' must be a non-empty string")

    context = data.get("context")
    if not isinstance(context, dict):
        issues.append("Field 'context' must be a JSON object containing task parameters")
    elif not context:
        issues.append("Field 'context' must not be empty")

    return issues


def validate_handoff_response(data: dict[str, Any]) -> list[str]:
    """Validate a subagent handoff response artifact against mkl-subagent-handoff/v1."""
    issues = []
    if not isinstance(data, dict):
        return ["Payload must be a JSON object"]

    protocol = data.get("protocol")
    if protocol != PROTOCOL_VERSION:
        issues.append(
            f"Invalid or missing protocol: expected '{PROTOCOL_VERSION}', got '{protocol}'"
        )

    for key in ("task_id", "agent", "status", "summary"):
        val = data.get(key)
        if not isinstance(val, str) or not val.strip():
            issues.append(f"Field '{key}' must be a non-empty string")

    status = data.get("status")
    if status and status not in ALLOWED_STATUSES:
        issues.append(f"Invalid status '{status}': must be one of {sorted(ALLOWED_STATUSES)}")

    verdict = data.get("verdict")
    if verdict is not None and verdict not in ALLOWED_VERDICTS:
        issues.append(f"Invalid verdict '{verdict}': must be one of {sorted(ALLOWED_VERDICTS)}")

    findings = data.get("findings")
    if findings is not None and not isinstance(findings, list):
        issues.append("Field 'findings' must be a list of finding objects")

    artifacts = data.get("artifacts")
    if artifacts is not None and not isinstance(artifacts, dict):
        issues.append("Field 'artifacts' must be a key-value dictionary")

    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Standardized Subagent Handoff Protocol Validator and Dispatcher"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Request creation
    req_parser = subparsers.add_parser("create-request", help="Create a handoff request payload")
    req_parser.add_argument("--task-id", required=True, help="Unique task identifier")
    req_parser.add_argument("--delegator", required=True, help="Originating agent name")
    req_parser.add_argument("--target-agent", required=True, help="Target subagent name")
    req_parser.add_argument("--goal", required=True, help="Task objective for context")
    req_parser.add_argument("--scope", nargs="*", default=[], help="Scoped paths or files")

    # Response creation
    resp_parser = subparsers.add_parser(
        "create-response", help="Create a handoff response artifact"
    )
    resp_parser.add_argument("--task-id", required=True, help="Unique task identifier")
    resp_parser.add_argument("--agent", required=True, help="Subagent name")
    resp_parser.add_argument(
        "--status", choices=sorted(ALLOWED_STATUSES), default="COMPLETED", help="Execution status"
    )
    resp_parser.add_argument(
        "--verdict", choices=sorted(ALLOWED_VERDICTS), default="APPROVED", help="Review verdict"
    )
    resp_parser.add_argument("--summary", required=True, help="High level synthesis summary")

    # Validation
    val_parser = subparsers.add_parser("validate", help="Validate a request or response JSON")
    val_parser.add_argument(
        "--type", choices=["request", "response"], required=True, help="Schema type to validate"
    )
    val_parser.add_argument("file", help="Path to JSON file or '-' for stdin")

    args = parser.parse_args(argv)

    if args.command == "create-request":
        ctx: dict[str, Any] = {"goal": args.goal}
        if args.scope:
            ctx["scope_paths"] = args.scope
        req = SubagentHandoffRequest(
            task_id=args.task_id,
            delegator=args.delegator,
            target_agent=args.target_agent,
            context=ctx,
        )
        print(req.to_json())
        return 0

    if args.command == "create-response":
        resp = SubagentHandoffResponse(
            task_id=args.task_id,
            agent=args.agent,
            status=args.status,
            verdict=args.verdict,
            summary=args.summary,
        )
        print(resp.to_json())
        return 0

    if args.command == "validate":
        if args.file == "-":
            raw = sys.stdin.read()
        else:
            with open(args.file, encoding="utf-8") as f:
                raw = f.read()

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            sys.stderr.write(f"JSON syntax error: {exc}\n")
            return 1

        issues = (
            validate_handoff_request(parsed)
            if args.type == "request"
            else validate_handoff_response(parsed)
        )
        if issues:
            sys.stderr.write(f"Validation failed for {args.type} ({len(issues)} issues):\n")
            for issue in issues:
                sys.stderr.write(f"  - {issue}\n")
            return 1

        print(f"Valid {args.type} payload conforming to {PROTOCOL_VERSION}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
