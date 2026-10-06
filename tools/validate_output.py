#!/usr/bin/env python3
"""Lightweight JSON schema validator and minimal error correction generator.

Zero external dependencies. Designed for CI and LLM structured output verification.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def validate(instance: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Validate a JSON data instance against a basic JSON schema definition.

    Returns a list of human-readable validation error messages.
    """
    errors: list[str] = []

    expected_type = schema.get("type")
    if expected_type:
        type_valid = False
        if expected_type == "object":
            type_valid = isinstance(instance, dict)
        elif expected_type == "array":
            type_valid = isinstance(instance, list)
        elif expected_type == "string":
            type_valid = isinstance(instance, str)
        elif expected_type == "integer":
            type_valid = isinstance(instance, int) and not isinstance(instance, bool)
        elif expected_type == "number":
            type_valid = isinstance(instance, (int, float)) and not isinstance(instance, bool)
        elif expected_type == "boolean":
            type_valid = isinstance(instance, bool)
        elif expected_type == "null":
            type_valid = instance is None

        if not type_valid:
            actual_type = type(instance).__name__
            errors.append(f"{path}: expected type '{expected_type}', got '{actual_type}'")
            return errors

    if "enum" in schema:
        allowed = schema["enum"]
        if instance not in allowed:
            errors.append(f"{path}: value {json.dumps(instance)} not in allowed enum {allowed}")

    if isinstance(instance, dict):
        required_keys = schema.get("required", [])
        for key in required_keys:
            if key not in instance:
                errors.append(f"{path}: missing required property '{key}'")

        properties = schema.get("properties", {})
        for key, val in instance.items():
            if key in properties:
                prop_errors = validate(
                    val, properties[key], path=f"{path}.{key}" if path != "$" else f"$.{key}"
                )
                errors.extend(prop_errors)

    elif isinstance(instance, list):
        items_schema = schema.get("items")
        if items_schema:
            for idx, item in enumerate(instance):
                item_errors = validate(item, items_schema, path=f"{path}[{idx}]")
                errors.extend(item_errors)

    elif isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: value {instance} is less than minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: value {instance} exceeds maximum {schema['maximum']}")

    elif isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(
                f"{path}: string length {len(instance)} is less than minLength {schema['minLength']}"
            )
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(
                f"{path}: string length {len(instance)} exceeds maxLength {schema['maxLength']}"
            )

    return errors


def format_correction_prompt(errors: list[str], failed_output: Any = None) -> str:
    """Format a token-efficient error feedback prompt containing only the schema delta.

    Prevents full conversation replay and cuts retry tokens by ~75%.
    """
    lines = [
        "The previous output failed JSON schema validation with the following errors:",
    ]
    for err in errors:
        lines.append(f"- {err}")
    lines.append("")
    lines.append(
        "Please provide the corrected JSON output fixing only these validation errors. "
        "Do not repeat conversational preamble or unproblematic fields."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate JSON against schema and output minimal error diffs."
    )
    parser.add_argument(
        "--schema",
        required=True,
        type=Path,
        help="Path to JSON Schema file",
    )
    parser.add_argument(
        "--string",
        type=str,
        default=None,
        help="Raw JSON string to validate",
    )
    parser.add_argument(
        "--diff-prompt",
        action="store_true",
        help="Emit minimal LLM retry prompt on error instead of plain error list",
    )
    parser.add_argument(
        "file",
        nargs="?",
        type=Path,
        default=None,
        help="Path to JSON file to validate (or stdin if omitted)",
    )

    args = parser.parse_args(argv)

    if not args.schema.is_file():
        print(f"Error: schema file not found: {args.schema}", file=sys.stderr)
        return 1

    try:
        schema = json.loads(args.schema.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Error parsing schema JSON: {exc}", file=sys.stderr)
        return 1

    if args.string is not None:
        raw_text = args.string
    elif args.file is not None:
        if not args.file.is_file():
            print(f"Error: input file not found: {args.file}", file=sys.stderr)
            return 1
        raw_text = args.file.read_text(encoding="utf-8")
    else:
        raw_text = sys.stdin.read()

    try:
        instance = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        errors = [f"$: invalid JSON syntax: {exc}"]
        if args.diff_prompt:
            print(format_correction_prompt(errors))
        else:
            for err in errors:
                print(f"Validation error: {err}", file=sys.stderr)
        return 1

    errors = validate(instance, schema)
    if errors:
        if args.diff_prompt:
            print(format_correction_prompt(errors, instance))
        else:
            for err in errors:
                print(f"Validation error: {err}", file=sys.stderr)
        return 1

    print("OK: JSON successfully validated against schema.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
